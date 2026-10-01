// TinyXML2 does not resolve namespaces itself; resolve names against each
// element's ancestors so imported RDF retains its original namespace scope.
#include "xmp.h"
#include "../third_party/tinyxml2/tinyxml2.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <vector>

using namespace tinyxml2;
namespace {
const char *RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#";
const char *NOTE = "http://ns.adobe.com/xmp/note/";
const char *TIFF = "http://ns.adobe.com/tiff/1.0/";
const char *XML = "http://www.w3.org/XML/1998/namespace";

int fail(char *err, size_t n, const char *message) {
  if (n) std::snprintf(err, n, "cannot preserve XMP: %s", message);
  return -1;
}

bool declaration(const char *name) {
  return !std::strcmp(name, "xmlns") || !std::strncmp(name, "xmlns:", 6);
}

std::string binding(const XMLElement *element, const std::string &prefix) {
  if (prefix == "xml") return XML;
  const std::string key = prefix.empty() ? "xmlns" : "xmlns:" + prefix;
  for (const XMLNode *p = element; p; p = p->Parent()) {
    const XMLElement *e = p->ToElement();
    if (e && e->Attribute(key.c_str())) return e->Attribute(key.c_str());
  }
  return "";
}

std::string expanded(const XMLElement *e, const char *name, bool attribute = false) {
  const std::string q = name;
  const size_t colon = q.find(':');
  const std::string prefix = colon == std::string::npos ? "" : q.substr(0, colon);
  const std::string uri = attribute && colon == std::string::npos ? "" : binding(e, prefix);
  // An undeclared prefix is not a valid namespace-qualified XML name.
  if (colon != std::string::npos && uri.empty()) return "!" + q;
  return uri + "\n" + (colon == std::string::npos ? q : q.substr(colon + 1));
}

bool named(const XMLElement *e, const char *name, const char *uri, const char *local,
           bool attribute = false) {
  return expanded(e, name, attribute) == std::string(uri) + "\n" + local;
}

std::string inherited(const XMLElement *element, const char *name) {
  for (const XMLNode *p = element; p; p = p->Parent()) {
    const XMLElement *e = p->ToElement();
    if (e && e->Attribute(name)) return e->Attribute(name);
  }
  return "";
}

template <typename F> void walk(XMLElement *e, F fn) {
  if (!e) return;
  fn(e);
  for (XMLElement *c = e->FirstChildElement(); c; c = c->NextSiblingElement()) walk(c, fn);
}

bool xml_character(unsigned long c) {
  return c == 9 || c == 10 || c == 13 || (c >= 0x20 && c <= 0xD7FF) ||
         (c >= 0xE000 && c <= 0xFFFD) || (c >= 0x10000 && c <= 0x10FFFF);
}

bool valid_utf8(const uint8_t *data, size_t len) {
  for (size_t i = 0; i < len;) {
    const unsigned char first = data[i++];
    unsigned long c = first;
    unsigned count = 0;
    if (first >= 0xC2 && first <= 0xDF) { count = 1; c &= 0x1F; }
    else if (first >= 0xE0 && first <= 0xEF) { count = 2; c &= 0x0F; }
    else if (first >= 0xF0 && first <= 0xF4) { count = 3; c &= 7; }
    else if (first >= 0x80) return false;
    if (count > len - i) return false;
    for (unsigned n = 0; n < count; ++n) {
      const unsigned char next = data[i++];
      if ((next & 0xC0) != 0x80) return false;
      c = (c << 6) | (next & 0x3F);
    }
    if ((count == 1 && c < 0x80) || (count == 2 && c < 0x800) ||
        (count == 3 && c < 0x10000) || !xml_character(c)) return false;
  }
  return true;
}

// TinyXML2 treats all processing instructions as declarations and disallows
// them after the root. XMP's trailing <?xpacket end=...?> is legal XML. Remove
// PIs (which are not RDF properties) in the parsing copy, leaving comments,
// CDATA and the XML declaration intact. Check entities explicitly because
// TinyXML2 otherwise accepts unknown entities as literal text.
bool parsing_copy(const uint8_t *data, size_t len, std::string &out) {
  const std::string input(reinterpret_cast<const char *>(data), len);
  for (size_t i = 0; i < len;) {
    const char *closing = nullptr;
    size_t opening = 0;
    if (input.compare(i, 4, "<!--") == 0) { closing = "-->"; opening = 4; }
    else if (input.compare(i, 9, "<![CDATA[") == 0) { closing = "]]>"; opening = 9; }
    if (closing) {
      const size_t end = input.find(closing, i + opening);
      if (end == std::string::npos) return false;
      out.append(input, i, end + 3 - i);
      i = end + 3;
      continue;
    }
    if (input.compare(i, 2, "<?") == 0) {
      const size_t end = input.find("?>", i + 2);
      if (end == std::string::npos) return false;
      if (input.compare(i, 6, "<?xml ") == 0) out.append(input, i, end + 2 - i);
      i = end + 2;
      continue;
    }
    // XMP does not use DTDs; accepting unresolved custom entities could alter
    // their meaning when serializing a merged packet.
    if (input.compare(i, 2, "<!") == 0) return false;
    if (input[i] == '&') {
      const size_t end = input.find(';', i + 1);
      if (end == std::string::npos) return false;
      const std::string entity = input.substr(i + 1, end - i - 1);
      if (entity != "amp" && entity != "lt" && entity != "gt" && entity != "quot" && entity != "apos") {
        if (entity.size() < 2 || entity[0] != '#') return false;
        const bool hex = entity[1] == 'x';
        const std::string digits = entity.substr(hex ? 2 : 1);
        if (digits.empty() || digits.find_first_not_of(hex ? "0123456789abcdefABCDEF" : "0123456789") != std::string::npos) return false;
        if (!xml_character(std::strtoul(digits.c_str(), nullptr, hex ? 16 : 10))) return false;
      }
      out.append(input, i, end + 1 - i);
      i = end + 1;
      continue;
    }
    if (static_cast<unsigned char>(input[i]) < 0x20 && !xml_character(input[i])) return false;
    out += input[i++];
  }
  return true;
}

bool parse(XMLDocument &doc, const uint8_t *data, size_t len) {
  if (!data || !len || !valid_utf8(data, len)) return false;
  std::string input;
  if (!parsing_copy(data, len, input) || doc.Parse(input.data(), input.size()) != XML_SUCCESS || !doc.RootElement()) return false;
  if (doc.RootElement()->NextSiblingElement()) return false;
  bool valid = true;
  walk(doc.RootElement(), [&](XMLElement *e) {
    if (expanded(e, e->Name())[0] == '!') valid = false;
    std::map<std::string, bool> attributes;
    for (const XMLAttribute *a = e->FirstAttribute(); a; a = a->Next()) {
      if (declaration(a->Name())) continue;
      const std::string name = expanded(e, a->Name(), true);
      if (name[0] == '!' || !attributes.emplace(name, true).second) valid = false;
    }
  });
  return valid;
}

XMLElement *rdf(XMLDocument &doc) {
  XMLElement *found = nullptr;
  int count = 0;
  walk(doc.RootElement(), [&](XMLElement *e) {
    if (named(e, e->Name(), RDF, "RDF")) { found = e; ++count; }
  });
  return count == 1 ? found : nullptr;
}

bool transport(const XMLElement *e, const char *name, bool attr = false) {
  return named(e, name, NOTE, "HasExtendedXMP", attr);
}

// Length-prefix values so arbitrary strings cannot collide with delimiters.
std::string token(const std::string &s) { return std::to_string(s.size()) + ":" + s; }

std::string value(const XMLElement *e) {
  std::vector<std::string> attributes;
  for (const XMLAttribute *a = e->FirstAttribute(); a; a = a->Next()) {
    if (!declaration(a->Name())) attributes.push_back(token(expanded(e, a->Name(), true)) + token(a->Value()));
  }
  std::sort(attributes.begin(), attributes.end());
  std::string body;
  for (const XMLNode *n = e->FirstChild(); n; n = n->NextSibling()) {
    if (n->ToElement()) body += "E" + token(expanded(n->ToElement(), n->Value())) + token(value(n->ToElement()));
    else if (n->ToText()) {
      const std::string text = n->Value();
      if (e->FirstChildElement() && text.find_first_not_of(" \t\r\n") == std::string::npos) continue;
      body += "T" + token(text);
    }
  }
  // Attribute-form simple properties and element-form simple properties have
  // the same RDF value. Comments/processing instructions are not properties.
  if (attributes.empty() && !e->FirstChildElement()) {
    std::string text;
    for (const XMLNode *n = e->FirstChild(); n; n = n->NextSibling()) if (n->ToText()) text += n->Value();
    return "S" + token(text);
  }
  std::string out = "C";
  for (const std::string &a : attributes) out += token(a);
  return out + token(body);
}

void preserve_scope(const XMLElement *source, XMLElement *copy) {
  std::map<std::string, std::string> scope;
  for (const XMLNode *p = source; p; p = p->Parent()) {
    const XMLElement *e = p->ToElement();
    if (!e) continue;
    for (const XMLAttribute *a = e->FirstAttribute(); a; a = a->Next()) {
      if (declaration(a->Name())) scope.emplace(a->Name(), a->Value());
    }
  }
  // Prevent the destination's default namespace from changing unprefixed names.
  if (!scope.count("xmlns")) scope["xmlns"] = "";
  for (const auto &entry : scope) copy->SetAttribute(entry.first.c_str(), entry.second.c_str());
  for (const char *name : {"xml:lang", "xml:base"}) {
    const std::string v = inherited(source, name);
    if (!copy->Attribute(name) && !v.empty()) copy->SetAttribute(name, v.c_str());
  }
}

// Deduplicate properties across descriptions for the same RDF subject, while
// retaining each description's namespace/qualifier scope and nested content.
bool collect(XMLElement *root, std::map<std::string, std::string> &properties) {
  for (XMLElement *d = root->FirstChildElement(); d; d = d->NextSiblingElement()) {
    if (!named(d, d->Name(), RDF, "Description")) return false;
    std::string subject;
    for (const XMLAttribute *a = d->FirstAttribute(); a; a = a->Next()) {
      if (named(d, a->Name(), RDF, "about", true)) subject = a->Value();
      else if (named(d, a->Name(), RDF, "nodeID", true)) return false;
    }
    auto add = [&](const std::string &key, const std::string &v, const XMLElement *owner) {
      const std::string full_key = token(subject) + token(key);
      const std::string full_value = token(inherited(owner, "xml:lang")) + token(inherited(owner, "xml:base")) + v;
      const auto old = properties.find(full_key);
      if (old == properties.end()) { properties[full_key] = full_value; return 1; }
      return old->second == full_value ? 0 : -1;
    };
    for (const XMLAttribute *a = d->FirstAttribute(); a;) {
      const XMLAttribute *next = a->Next();
      const std::string name = a->Name();
      if (transport(d, name.c_str(), true)) d->DeleteAttribute(name.c_str());
      else if (!declaration(name.c_str()) && expanded(d, name.c_str(), true).compare(0, std::strlen(RDF) + 1, std::string(RDF) + "\n") != 0 &&
               expanded(d, name.c_str(), true).compare(0, std::strlen(XML) + 1, std::string(XML) + "\n") != 0) {
        const int rc = add(expanded(d, name.c_str(), true), "S" + token(a->Value()), d);
        if (rc < 0) return false;
        if (!rc) d->DeleteAttribute(name.c_str());
      }
      a = next;
    }
    for (XMLElement *e = d->FirstChildElement(); e;) {
      XMLElement *next = e->NextSiblingElement();
      if (transport(e, e->Name())) d->DeleteChild(e);
      else {
        const int rc = add(expanded(e, e->Name()), value(e), e);
        if (rc < 0) return false;
        if (!rc) d->DeleteChild(e);
      }
      e = next;
    }
  }
  return true;
}

int serialize(XMLDocument &doc, uint8_t **out, size_t *len, char *err, size_t err_len) {
  XMLPrinter printer(nullptr, true);
  doc.Print(&printer);
  const size_t size = static_cast<size_t>(printer.CStrSize() - 1);
  uint8_t *copy = static_cast<uint8_t *>(std::malloc(size));
  if (!copy) return fail(err, err_len, "out of memory");
  std::memcpy(copy, printer.CStr(), size);
  *out = copy;
  *len = size;
  return 0;
}
}  // namespace

extern "C" int xmp_extended_guid(const uint8_t *x, size_t len, char guid[33], char *err, size_t err_len) {
  guid[0] = 0;
  if (!len) return 0;
  XMLDocument doc;
  if (!parse(doc, x, len)) return fail(err, err_len, "invalid XML");
  bool valid = true;
  auto reference = [&](const char *s) {
    if (!s || std::strlen(s) != 32) { valid = false; return; }
    char normal[33];
    for (size_t i = 0; i < 32; ++i) {
      const char c = s[i];
      if (!((c >= '0' && c <= '9') || (c >= 'A' && c <= 'F') || (c >= 'a' && c <= 'f'))) valid = false;
      normal[i] = c >= 'a' && c <= 'f' ? c - 'a' + 'A' : c;
    }
    normal[32] = 0;
    if (guid[0] && std::strcmp(guid, normal)) valid = false;
    std::memcpy(guid, normal, sizeof normal);
  };
  walk(doc.RootElement(), [&](XMLElement *e) {
    if (transport(e, e->Name())) reference(e->GetText());
    for (const XMLAttribute *a = e->FirstAttribute(); a; a = a->Next()) if (transport(e, a->Name(), true)) reference(a->Value());
  });
  if (!valid) return fail(err, err_len, "invalid HasExtendedXMP reference");
  return guid[0] ? 1 : 0;
}

extern "C" int xmp_merge_extended(const uint8_t *base, size_t base_len, const uint8_t *ext,
                                  size_t ext_len, uint8_t **out, size_t *out_len, char *err, size_t err_len) {
  XMLDocument a, b;
  if (!parse(a, base, base_len) || !parse(b, ext, ext_len)) return fail(err, err_len, "invalid extended XMP XML");
  XMLElement *ar = rdf(a), *br = rdf(b);
  if (!ar || !br) return fail(err, err_len, "expected one RDF container per XMP packet");
  std::map<std::string, std::string> properties;
  if (!collect(ar, properties)) return fail(err, err_len, "conflicting or unsupported RDF properties");
  // Materialize inherited scopes before moving each description into the base.
  for (XMLElement *d = br->FirstChildElement(); d; d = d->NextSiblingElement()) {
    XMLElement *copy = d->DeepClone(&a)->ToElement();
    preserve_scope(d, copy);
    ar->InsertEndChild(copy);
  }
  properties.clear();
  if (!collect(ar, properties)) return fail(err, err_len, "conflicting or unsupported RDF properties");
  return serialize(a, out, out_len, err, err_len);
}

extern "C" int xmp_orientation(const uint8_t *x, size_t len) {
  XMLDocument doc;
  if (!parse(doc, x, len)) return 0;
  int orientation = 0;
  auto read = [&](const char *v) {
    if (!orientation && v && v[0] >= '1' && v[0] <= '8' && !v[1]) orientation = v[0] - '0';
  };
  walk(doc.RootElement(), [&](XMLElement *e) {
    if (named(e, e->Name(), TIFF, "Orientation")) read(e->GetText());
    for (const XMLAttribute *a = e->FirstAttribute(); a; a = a->Next()) if (named(e, a->Name(), TIFF, "Orientation", true)) read(a->Value());
  });
  return orientation;
}

extern "C" int xmp_reset_orientation(uint8_t **x, size_t *len, char *err, size_t err_len) {
  XMLDocument doc;
  if (!parse(doc, *x, *len)) return fail(err, err_len, "invalid XML");
  bool changed = false;
  walk(doc.RootElement(), [&](XMLElement *e) {
    if (named(e, e->Name(), TIFF, "Orientation") && e->GetText() && std::strcmp(e->GetText(), "1")) {
      e->SetText("1"); changed = true;
    }
    for (const XMLAttribute *a = e->FirstAttribute(); a; a = a->Next()) {
      if (named(e, a->Name(), TIFF, "Orientation", true) && std::strcmp(a->Value(), "1")) {
        e->SetAttribute(a->Name(), "1"); changed = true;
      }
    }
  });
  if (!changed) return 0;
  uint8_t *copy = nullptr;
  size_t size = 0;
  if (serialize(doc, &copy, &size, err, err_len)) return -1;
  std::free(*x);
  *x = copy;
  *len = size;
  return 1;
}
