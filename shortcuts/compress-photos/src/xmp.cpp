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
#include <utility>
#include <vector>

using namespace tinyxml2;
namespace {
const char *RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#";
const char *NOTE = "http://ns.adobe.com/xmp/note/";
const char *TIFF = "http://ns.adobe.com/tiff/1.0/";
const char *XAP = "http://ns.adobe.com/xap/1.0/";
const char *PHOTOSHOP = "http://ns.adobe.com/photoshop/1.0/";
const char *EXIF = "http://ns.adobe.com/exif/1.0/";
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
  const bool elements = e->FirstChildElement() != nullptr;  // once: it walks the children
  std::string body;
  for (const XMLNode *n = e->FirstChild(); n; n = n->NextSibling()) {
    if (n->ToElement()) body += "E" + token(expanded(n->ToElement(), n->Value())) + token(value(n->ToElement()));
    else if (n->ToText()) {
      const std::string text = n->Value();
      if (elements && text.find_first_not_of(" \t\r\n") == std::string::npos) continue;
      body += "T" + token(text);
    }
  }
  // Attribute-form simple properties and element-form simple properties have
  // the same RDF value. Comments/processing instructions are not properties.
  if (attributes.empty() && !elements) {
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

// Orientation and the extended-XMP reference are found by a tolerant scanner
// over the packet's own bytes, and orientation is reset by replacing only its
// value: a packet is never rewritten or rejected for this. Real-world XMP is
// often not strict XML (trailing NULs, Latin-1 text, HTML entities), so the
// scanner follows only markup: tags, quoted attribute values, comments, CDATA,
// processing instructions and namespace declarations. As in other XMP readers,
// only top-level properties count: text in descriptions, comments or other
// attributes, and fields of structures, are never mistaken for one.
namespace {
struct Name {
  std::string uri, prefix, local;
};

// Part of a value: character data, whose references are decoded, or the inside
// of a CDATA section, which is literal.
struct Run {
  size_t begin, end;
  bool literal;
};

struct Property {
  Name name;
  std::vector<Run> runs;  // an attribute value, or an element's text and CDATA
};

// A name, by namespace; an undeclared conventional prefix (e.g. "tiff:")
// counts too, since malformed packets often omit the declaration.
bool is(const Name &n, const char *uri, const char *prefix, const char *local) {
  return n.local == local && (n.uri == uri || (n.uri.empty() && n.prefix == prefix));
}

bool whitespace(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }

// The ASCII character a reference stands for, by the text between "&" and ";"
// ("amp", "#54" or "#x36"); 0 for any other reference.
char referenced(const std::string &name) {
  static const std::map<std::string, char> entities = {
      {"amp", '&'}, {"lt", '<'}, {"gt", '>'}, {"quot", '"'}, {"apos", '\''}};
  const auto entity = entities.find(name);
  if (entity != entities.end()) return entity->second;
  if (name.size() < 2 || name[0] != '#') return 0;
  const bool hex = name[1] == 'x';
  const std::string digits = name.substr(hex ? 2 : 1);
  if (digits.empty() || digits.find_first_not_of(hex ? "0123456789abcdefABCDEF" : "0123456789") != std::string::npos)
    return 0;
  const unsigned long code = std::strtoul(digits.c_str(), nullptr, hex ? 16 : 10);
  return code < 0x80 ? static_cast<char>(code) : 0;
}

// One character of a value and the raw bytes it came from. References to
// ASCII characters are decoded; anything else stays as written.
struct Character {
  char c;
  size_t begin, end;
};

std::vector<Character> characters(const std::string &s, const std::vector<Run> &runs) {
  std::vector<Character> out;
  for (const Run &r : runs) {
    for (size_t i = r.begin; i < r.end;) {
      char c = s[i];
      size_t next = i + 1;
      if (c == '&' && !r.literal) {
        // The references decoded here are short, which bounds the search.
        const size_t limit = std::min(r.end, i + 16);
        size_t semicolon = i + 1;
        while (semicolon < limit && s[semicolon] != ';') ++semicolon;
        const char decoded = semicolon < limit ? referenced(s.substr(i + 1, semicolon - i - 1)) : 0;
        if (decoded) {
          c = decoded;
          next = semicolon + 1;
        }
      }
      out.push_back({c, i, next});
      i = next;
    }
  }
  return out;
}

// A property's value: its characters without surrounding whitespace.
std::vector<Character> trimmed(const std::string &s, const Property &p) {
  std::vector<Character> v = characters(s, p.runs);
  const auto blank = [](const Character &c) { return whitespace(c.c); };
  v.erase(std::find_if_not(v.rbegin(), v.rend(), blank).base(), v.end());
  v.erase(v.begin(), std::find_if_not(v.begin(), v.end(), blank));
  return v;
}

// The top-level properties, in document order: the attributes and the child
// elements of each node element (rdf:Description) directly inside rdf:RDF. An
// element counts only if it holds nothing but text, CDATA, comments and
// processing instructions. Stops at markup it can't follow.
std::vector<Property> scan(const std::string &s) {
  struct Element {
    std::string qualified;  // as written, to match its end tag
    Name name;
    std::vector<std::pair<std::string, std::string>> declarations;
    std::vector<Run> text;
    bool children;
  };
  std::vector<Property> found;
  std::vector<Element> open;
  auto resolve = [&](const std::string &qualified, bool attribute) -> Name {
    const size_t colon = qualified.find(':');
    Name n;
    n.prefix = colon == std::string::npos ? "" : qualified.substr(0, colon);
    n.local = colon == std::string::npos ? qualified : qualified.substr(colon + 1);
    // Unprefixed attributes have no namespace.
    if (attribute && n.prefix.empty()) return n;
    for (auto e = open.rbegin(); e != open.rend(); ++e)
      for (const auto &d : e->declarations)
        if (d.first == n.prefix) {
          n.uri = d.second;
          return n;
        }
    if (n.prefix == "xml") n.uri = XML;
    return n;
  };
  // Whether open[i] is directly inside rdf:RDF.
  auto in_rdf = [&](size_t i) { return i >= 1 && is(open[i - 1].name, RDF, "rdf", "RDF"); };
  // The position just past `close`, searching from `from`; npos if absent.
  auto past = [&](const char *close, size_t from) {
    const size_t at = s.find(close, from);
    return at == std::string::npos ? at : at + std::strlen(close);
  };
  const size_t len = s.size();
  size_t i = 0;
  while (i < len) {
    size_t end = 0;
    if (!s.compare(i, 4, "<!--")) {
      end = past("-->", i + 4);
    } else if (!s.compare(i, 9, "<![CDATA[")) {
      end = past("]]>", i + 9);  // text, never markup
      if (end != std::string::npos && !open.empty() && !open.back().children)
        open.back().text.push_back({i + 9, end - 3, true});
    } else if (!s.compare(i, 2, "<?")) {
      end = past("?>", i + 2);
    } else if (!s.compare(i, 2, "<!")) {
      end = past(">", i + 2);
    } else if (!s.compare(i, 2, "</")) {
      end = past(">", i + 2);
      if (end == std::string::npos) break;
      size_t n = i + 2;
      while (n < end - 1 && !whitespace(s[n])) ++n;
      const std::string qualified = s.substr(i + 2, n - i - 2);
      // Close the element, and any left open inside it; ignore a stray end tag.
      for (size_t k = open.size(); k-- > 0;) {
        if (open[k].qualified != qualified) continue;
        const Element &e = open[k];
        if (!e.children && k >= 1 && in_rdf(k - 1)) found.push_back({e.name, e.text});
        open.erase(open.begin() + k, open.end());
        break;
      }
    } else if (s[i] != '<') {
      end = s.find('<', i);
      if (!open.empty() && !open.back().children)
        open.back().text.push_back({i, end == std::string::npos ? len : end, false});
    } else {
      // A start tag: its name, then name="value" attributes.
      size_t j = i + 1;
      while (j < len && !whitespace(s[j]) && s[j] != '/' && s[j] != '>') ++j;
      Element element = {s.substr(i + 1, j - i - 1), Name(), {}, {}, false};
      std::vector<std::pair<std::string, Run>> attributes;
      bool empty = false;
      for (;;) {
        while (j < len && whitespace(s[j])) ++j;
        if (j >= len) return found;
        if (s[j] == '>') { ++j; break; }
        if (!s.compare(j, 2, "/>")) { j += 2; empty = true; break; }
        const size_t a = j;
        while (j < len && !whitespace(s[j]) && s[j] != '=' && s[j] != '/' && s[j] != '>') ++j;
        const std::string attribute = s.substr(a, j - a);
        while (j < len && whitespace(s[j])) ++j;
        if (j >= len || s[j] != '=') return found;
        ++j;
        while (j < len && whitespace(s[j])) ++j;
        if (j >= len || (s[j] != '"' && s[j] != '\'')) return found;
        const size_t close = s.find(s[j], j + 1);
        if (close == std::string::npos) return found;
        const Run value = {j + 1, close, false};
        if (attribute == "xmlns" || !attribute.compare(0, 6, "xmlns:")) {
          std::string uri;  // references decoded: "&#47;" is "/"
          for (const Character &c : characters(s, {value})) uri += c.c;
          element.declarations.emplace_back(attribute == "xmlns" ? "" : attribute.substr(6), uri);
        } else {
          attributes.emplace_back(attribute, value);
        }
        j = close + 1;
      }
      // Far deeper than XMP goes; this bounds the search for end tags.
      if (open.size() >= 256) return found;
      if (!open.empty()) {
        open.back().children = true;
        open.back().text.clear();
      }
      open.push_back(std::move(element));
      open.back().name = resolve(open.back().qualified, false);
      if (in_rdf(open.size() - 1))
        for (const auto &a : attributes) found.push_back({resolve(a.first, true), {a.second}});
      if (empty) open.pop_back();
      end = j;
    }
    if (end == std::string::npos) break;
    i = end;
  }
  return found;
}

// The orientation (1-8) a property holds, or 0; `at` gets the raw bytes of its
// digit (e.g. "6", or "&#54;").
int orientation(const std::string &s, const Property &p, std::pair<size_t, size_t> *at = nullptr) {
  if (!is(p.name, TIFF, "tiff", "Orientation")) return 0;
  const std::vector<Character> v = trimmed(s, p);
  if (v.size() != 1 || v[0].c < '1' || v[0].c > '8') return 0;
  if (at) *at = std::make_pair(v[0].begin, v[0].end);
  return v[0].c - '0';
}

// Replaces each span of the packet `s` (in order, not overlapping) with
// `text`, in the malloc-owned copy *x. Returns the number of spans, or -1 if
// out of memory (*x unchanged).
int replace_spans(uint8_t **x, size_t *len, const std::string &s,
                  const std::vector<std::pair<size_t, size_t>> &spans, const std::string &text) {
  if (spans.empty()) return 0;
  std::string out;
  size_t from = 0;
  for (const auto &d : spans) {
    out.append(s, from, d.first - from);
    out += text;
    from = d.second;
  }
  out.append(s, from, std::string::npos);
  uint8_t *copy = static_cast<uint8_t *>(std::malloc(out.size()));
  if (!copy) return -1;
  std::memcpy(copy, out.data(), out.size());
  std::free(*x);
  *x = copy;
  *len = out.size();
  return static_cast<int>(spans.size());
}
}  // namespace

extern "C" int xmp_orientation(const uint8_t *x, size_t len) {
  const std::string s(reinterpret_cast<const char *>(x), len);
  for (const Property &p : scan(s))
    if (const int o = orientation(s, p)) return o;
  return 0;
}

extern "C" int xmp_has_extended_reference(const uint8_t *x, size_t len) {
  const std::string s(reinterpret_cast<const char *>(x), len);
  for (const Property &p : scan(s))
    if (is(p.name, NOTE, "xmpNote", "HasExtendedXMP") && !trimmed(s, p).empty()) return 1;
  return 0;
}

extern "C" int xmp_reset_orientation(uint8_t **x, size_t *len) {
  const std::string s(reinterpret_cast<const char *>(*x), *len);
  // The digit of each orientation other than 1, in document order.
  std::vector<std::pair<size_t, size_t>> digits;
  for (const Property &p : scan(s)) {
    std::pair<size_t, size_t> at;
    if (orientation(s, p, &at) > 1) digits.push_back(at);
  }
  return replace_spans(x, len, s, digits, "1");
}

extern "C" int xmp_set_dates(uint8_t **x, size_t *len, const char *date) {
  const std::string s(reinterpret_cast<const char *>(*x), *len);
  std::vector<std::pair<size_t, size_t>> values;
  for (const Property &p : scan(s)) {
    if (!is(p.name, XAP, "xmp", "CreateDate") && !is(p.name, PHOTOSHOP, "photoshop", "DateCreated") &&
        !is(p.name, EXIF, "exif", "DateTimeOriginal") && !is(p.name, EXIF, "exif", "DateTimeDigitized"))
      continue;
    const std::vector<Character> v = trimmed(s, p);
    if (v.empty()) continue;
    for (const Run &r : p.runs)
      if (v.front().begin >= r.begin && v.back().end <= r.end) values.emplace_back(v.front().begin, v.back().end);
  }
  std::sort(values.begin(), values.end());
  return replace_spans(x, len, s, values, date);
}
