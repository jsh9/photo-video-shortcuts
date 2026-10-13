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
const char *DC = "http://purl.org/dc/elements/1.1/";
const char *IPTC_CORE = "http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/";
const char *IPTC_EXT = "http://iptc.org/std/Iptc4xmpExt/2008-02-29/";

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

// An item of an array (rdf:li holding text), with its xml:lang.
struct Item {
  std::vector<Run> runs;
  std::string lang;  // its effective xml:lang (its own, else inherited)
};

struct Property {
  Name name;
  std::vector<Run> runs;  // an attribute value, or an element's text and CDATA
  // Where the property is written: the attribute (name="value"), or the
  // element from its start tag to the end of its end tag.
  size_t begin, end;
  bool structured;          // an element holding other elements (rdf:Alt, ...)
  std::vector<Item> items;  // the text items of its arrays, if structured
  // It holds a value the scanner can't read as text (an array item holding
  // elements but no rdf:value): present, but never equal to a text.
  bool opaque;
};

Property property(const Name &name, const std::vector<Run> &runs, size_t begin, size_t end, bool structured,
                  const std::vector<Item> &items, bool opaque) {
  Property p;
  p.name = name;
  p.runs = runs;
  p.begin = begin;
  p.end = end;
  p.structured = structured;
  p.items = items;
  p.opaque = opaque;
  return p;
}

// What edits need besides the properties: where rdf:RDF ends (its end tag;
// npos if none was found) or, for an empty rdf:RDF written as one tag
// ("<rdf:RDF .../>"), where its "/>" is and its name as written; and the first
// node element's rdf:about value as written.
struct Layout {
  size_t rdf_end;
  size_t rdf_empty;  // npos unless rdf:RDF is one empty tag
  std::string rdf_qualified;
  std::string about;
  bool has_about;
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

// The top-level properties: the attributes and the child elements of each
// node element (rdf:Description) directly inside rdf:RDF, an element when it
// closes. An element holding nothing but text, CDATA, comments and processing
// instructions has that text as its value; one holding elements is structured,
// with the text items of its arrays (rdf:li), a qualified item's being its
// rdf:value (an element or an attribute); an item holding elements or fields
// but no rdf:value makes it opaque. Stops at markup it can't follow.
// `layout`, if given, gets where rdf:RDF ends and the first rdf:about.
std::vector<Property> scan(const std::string &s, Layout *layout = nullptr) {
  struct Element {
    std::string qualified;  // as written, to match its end tag
    Name name;
    std::vector<std::pair<std::string, std::string>> declarations;
    std::vector<Run> text;
    bool children;
    size_t start;      // its '<'
    std::string lang;  // its xml:lang
    std::vector<Item> items;
    bool has_value;  // an rdf:li: an rdf:value inside it was read
    bool opaque;     // a top-level property: see Property
    Run value_attr;  // its rdf:value attribute, if has_value_attr
    bool has_value_attr;
    bool fields;  // it has attributes that are fields or qualifiers (not rdf:, xml:lang)
    size_t num_children;   // the elements directly inside it
    bool empty_container;  // one of them is an rdf:Alt, rdf:Bag or rdf:Seq holding no element
  };
  struct Attribute {
    std::string qualified;
    Run value;
    size_t start;
  };
  if (layout) {
    layout->rdf_end = std::string::npos;
    layout->rdf_empty = std::string::npos;
    layout->rdf_qualified.clear();
    layout->about.clear();
    layout->has_about = false;
  }
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
  // The top-level property open[k] is in (k itself excluded), 0 if none.
  auto property_of = [&](size_t k) -> size_t {
    for (size_t p = k; p-- > 1;)
      if (in_rdf(p - 1)) return p;
    return 0;
  };
  auto blank = [&](const std::vector<Run> &runs) {
    for (const Run &r : runs)
      for (size_t c = r.begin; c < r.end; ++c)
        if (!whitespace(s[c])) return false;
    return true;
  };
  // Closes open[k], which ends at `end` (its end tag starts at `at`, npos
  // for an empty-element tag). A top-level property is found, its value its
  // text or an rdf:value attribute. Inside one, an array item (rdf:li) or a
  // qualified value (an rdf:value element, or an element with an rdf:value
  // attribute) adds its text as an item when it can be read: it has text, or
  // it is plainly empty. One that can't (fields or a URI without text, or
  // elements but no rdf:value read) makes the property opaque, so that it is
  // never taken for absent or for Photos' value; so does a property holding
  // elements but no item at all, unless they are one empty array (an empty
  // rdf:Alt or rdf:Bag is plainly empty). rdf:RDF's end tag goes to `layout`.
  auto close_element = [&](size_t k, size_t end, size_t at) {
    Element &e = open[k];
    if (k >= 1) {
      Element &parent = open[k - 1];
      parent.num_children++;
      if (!e.children && !e.fields &&
          (is(e.name, RDF, "rdf", "Alt") || is(e.name, RDF, "rdf", "Bag") || is(e.name, RDF, "rdf", "Seq")))
        parent.empty_container = true;
    }
    std::vector<Run> value = e.children ? std::vector<Run>() : e.text;
    if (e.has_value_attr) value = std::vector<Run>(1, e.value_attr);
    // fields or qualifiers (rdf:resource among them), but no text
    const bool unreadable = e.fields && blank(value);
    if (k >= 1 && in_rdf(k - 1)) {
      const bool no_items = e.children && e.items.empty() && !(e.num_children == 1 && e.empty_container);
      found.push_back(property(e.name, e.children ? std::vector<Run>() : value, e.start, end, e.children, e.items,
                               e.opaque || (unreadable && !e.children) || no_items));
    } else if (is(e.name, RDF, "rdf", "li")) {
      if (const size_t p = property_of(k)) {
        if (e.children && !e.has_value_attr) {
          if (!e.has_value) open[p].opaque = true;  // no rdf:value read inside
        } else if (unreadable) {
          open[p].opaque = true;
        } else {
          Item item;
          item.runs = value;
          item.lang = e.lang;
          open[p].items.push_back(item);
        }
      }
    } else if (is(e.name, RDF, "rdf", "value") || e.has_value_attr) {
      // the item of the rdf:li it is in (or of the property itself); its
      // language is that rdf:li's unless it has its own
      if (const size_t p = property_of(k)) {
        size_t li = 0;
        for (size_t q = k; q-- > p + 1;)
          if (is(open[q].name, RDF, "rdf", "li")) {
            li = q;
            break;
          }
        if ((e.children && !e.has_value_attr) || unreadable) {
          open[p].opaque = true;
        } else {
          Item item;
          item.runs = value;
          item.lang = e.lang;
          open[p].items.push_back(item);
          if (li) open[li].has_value = true;
        }
      }
    } else if (layout && at != std::string::npos && layout->rdf_end == std::string::npos &&
               is(e.name, RDF, "rdf", "RDF")) {
      layout->rdf_end = at;
    }
  };
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
        close_element(k, end, i);
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
      Element element = {s.substr(i + 1, j - i - 1), Name(), {}, {}, false, i, "", {}, false, false, Run(), false,
                         false, 0, false};
      std::vector<Attribute> attributes;
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
          attributes.push_back({attribute, value, a});
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
      // xml:lang is inherited (an rdf:Alt may carry its items'), unless the
      // element has its own, "" included.
      if (open.size() >= 2) open.back().lang = open[open.size() - 2].lang;
      for (const Attribute &a : attributes) {
        const Name name = resolve(a.qualified, true);
        if (is(name, XML, "xml", "lang")) {
          open.back().lang.clear();
          for (const Character &c : characters(s, {a.value})) open.back().lang += c.c;
        } else if (is(name, RDF, "rdf", "value")) {
          open.back().value_attr = a.value;
          open.back().has_value_attr = true;
        } else if (!(name.uri == RDF || (name.uri.empty() && name.prefix == "rdf")) ||
                   is(name, RDF, "rdf", "resource")) {
          // a field or qualifier (rdf:resource: a value that isn't text)
          open.back().fields = true;
        }
        if (!in_rdf(open.size() - 1)) continue;
        // A node element's attributes are properties; its rdf:about is kept for
        // a node element added later.
        if (layout && !layout->has_about && is(name, RDF, "rdf", "about")) {
          layout->about = s.substr(a.value.begin, a.value.end - a.value.begin);
          layout->has_about = true;
        }
        found.push_back(property(name, {a.value}, a.start, a.value.end + 1, false, {}, false));
      }
      if (empty) {
        // An empty-element tag closes at once (<dc:title/>, <rdf:li
        // rdf:value="..."/>); an empty rdf:RDF has its "/>" just before j.
        close_element(open.size() - 1, j, std::string::npos);
        if (layout && layout->rdf_empty == std::string::npos && is(open.back().name, RDF, "rdf", "RDF")) {
          layout->rdf_empty = j - 2;
          layout->rdf_qualified = open.back().qualified;
        }
        open.pop_back();
      }
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

void append_utf8(std::string &out, unsigned long c) {
  if (c < 0x80) {
    out += static_cast<char>(c);
  } else if (c < 0x800) {
    out += static_cast<char>(0xC0 | (c >> 6));
    out += static_cast<char>(0x80 | (c & 0x3F));
  } else if (c < 0x10000) {
    out += static_cast<char>(0xE0 | (c >> 12));
    out += static_cast<char>(0x80 | ((c >> 6) & 0x3F));
    out += static_cast<char>(0x80 | (c & 0x3F));
  } else {
    out += static_cast<char>(0xF0 | (c >> 18));
    out += static_cast<char>(0x80 | ((c >> 12) & 0x3F));
    out += static_cast<char>(0x80 | ((c >> 6) & 0x3F));
    out += static_cast<char>(0x80 | (c & 0x3F));
  }
}

// A value's text: every reference decoded ("&#233;" too, unlike characters()),
// CDATA as it is, without surrounding whitespace.
std::string text_of(const std::string &s, const std::vector<Run> &runs) {
  static const std::map<std::string, char> entities = {
      {"amp", '&'}, {"lt", '<'}, {"gt", '>'}, {"quot", '"'}, {"apos", '\''}};
  std::string out;
  for (const Run &r : runs) {
    if (r.literal) {
      out.append(s, r.begin, r.end - r.begin);
      continue;
    }
    for (size_t i = r.begin; i < r.end;) {
      const size_t semicolon = s[i] == '&' ? s.find(';', i + 1) : std::string::npos;
      if (semicolon != std::string::npos && semicolon < r.end && semicolon - i <= 12) {
        const std::string name = s.substr(i + 1, semicolon - i - 1);
        const auto entity = entities.find(name);
        if (entity != entities.end()) {
          out += entity->second;
          i = semicolon + 1;
          continue;
        }
        const bool hex = name.size() > 1 && (name[1] == 'x' || name[1] == 'X');
        const std::string digits = name.size() > 1 && name[0] == '#' ? name.substr(hex ? 2 : 1) : "";
        if (!digits.empty() && digits.find_first_not_of(hex ? "0123456789abcdefABCDEF" : "0123456789") == std::string::npos) {
          const unsigned long code = std::strtoul(digits.c_str(), nullptr, hex ? 16 : 10);
          if (xml_character(code)) {
            append_utf8(out, code);
            i = semicolon + 1;
            continue;
          }
        }
      }
      out += s[i++];
    }
  }
  const size_t first = out.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) return "";
  return out.substr(first, out.find_last_not_of(" \t\r\n") - first + 1);
}

// A language alternative's text (dc:title, dc:description): its x-default
// item, else its first; a simple value as it is.
std::string alt_text(const std::string &s, const Property &p) {
  if (!p.structured) return text_of(s, p.runs);
  for (const Item &item : p.items)
    if (item.lang == "x-default") return text_of(s, item.runs);
  return p.items.empty() ? "" : text_of(s, p.items.front().runs);
}

// `text` as an element's content: &, < and > escaped, a carriage return as a
// reference (a parser turns a literal one into a line feed), and what XML 1.0
// can't hold dropped (invalid UTF-8, control characters but tab and line feed).
std::string escaped(const char *text) {
  const uint8_t *p = reinterpret_cast<const uint8_t *>(text);
  const size_t n = std::strlen(text);
  std::string out;
  for (size_t i = 0; i < n;) {
    const uint8_t c = p[i];
    if (c >= 0x80) {
      const size_t k = c >= 0xC2 && c <= 0xDF ? 2 : c >= 0xE0 && c <= 0xEF ? 3 : c >= 0xF0 && c <= 0xF4 ? 4 : 0;
      if (k && k <= n - i && valid_utf8(p + i, k)) {
        out.append(text + i, k);
        i += k;
      } else {
        ++i;
      }
      continue;
    }
    if (c == '&') {
      out += "&amp;";
    } else if (c == '<') {
      out += "&lt;";
    } else if (c == '>') {
      out += "&gt;";
    } else if (c == '\r') {
      out += "&#xD;";
    } else if (c >= 0x20 || c == '\t' || c == '\n') {
      out += static_cast<char>(c);
    }
    ++i;
  }
  return out;
}

// A change to the packet: [begin, end) replaced with `text`.
struct Edit {
  size_t begin, end;
  std::string text;
};

bool edit_order(const Edit &a, const Edit &b) { return a.begin < b.begin; }

// The edit that removes a property, with the whitespace before it.
Edit removal(const std::string &s, const Property &p) {
  size_t begin = p.begin;
  while (begin > 0 && whitespace(s[begin - 1])) --begin;
  Edit e = {begin, p.end, ""};
  return e;
}

// Applies the edits (not overlapping) to the malloc-owned packet *x, a copy
// of `s`. Returns the number of edits, or -1 if out of memory (*x unchanged).
int apply_edits(uint8_t **x, size_t *len, const std::string &s, std::vector<Edit> edits) {
  if (edits.empty()) return 0;
  std::stable_sort(edits.begin(), edits.end(), edit_order);
  std::string out;
  size_t from = 0;
  for (const Edit &e : edits) {
    out.append(s, from, e.begin - from);
    out += e.text;
    from = e.end;
  }
  out.append(s, from, std::string::npos);
  uint8_t *copy = static_cast<uint8_t *>(std::malloc(out.size()));
  if (!copy) return -1;
  std::memcpy(copy, out.data(), out.size());
  std::free(*x);
  *x = copy;
  *len = out.size();
  return static_cast<int>(edits.size());
}

char *c_string(const std::string &v) {
  char *c = static_cast<char *>(std::malloc(v.size() + 1));
  if (c) std::memcpy(c, v.c_str(), v.size() + 1);
  return c;
}

// A property that tells where the photo was taken: the EXIF schema's GPS
// tags, and place names.
bool is_location(const Name &n) {
  if ((n.uri == EXIF || (n.uri.empty() && n.prefix == "exif")) && !n.local.compare(0, 3, "GPS")) return true;
  return is(n, PHOTOSHOP, "photoshop", "City") || is(n, PHOTOSHOP, "photoshop", "State") ||
         is(n, PHOTOSHOP, "photoshop", "Country") || is(n, IPTC_CORE, "Iptc4xmpCore", "Location") ||
         is(n, IPTC_CORE, "Iptc4xmpCore", "CountryCode") || is(n, IPTC_EXT, "Iptc4xmpExt", "LocationCreated") ||
         is(n, IPTC_EXT, "Iptc4xmpExt", "LocationShown");
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

extern "C" void xmp_dc_free(xmp_dc_t *dc) {
  std::free(dc->title);
  std::free(dc->description);
  for (size_t k = 0; k < dc->num_subject; ++k) std::free(dc->subject[k]);
  std::free(dc->subject);
  std::memset(dc, 0, sizeof *dc);
}

extern "C" int xmp_dc_read(const uint8_t *x, size_t len, xmp_dc_t *dc) {
  std::memset(dc, 0, sizeof *dc);
  const std::string s(reinterpret_cast<const char *>(x), len);
  std::vector<std::string> subject;
  for (const Property &p : scan(s)) {
    const bool title = is(p.name, DC, "dc", "title"), description = is(p.name, DC, "dc", "description");
    if (!title && !description && !is(p.name, DC, "dc", "subject")) continue;
    int &state = title ? dc->title_state : description ? dc->description_state : dc->subject_state;
    if (state) continue;  // the packet's first of each
    state = p.opaque ? 2 : 1;
    if (p.opaque) continue;
    if (title || description) {
      const std::string v = alt_text(s, p);
      if (v.empty()) continue;
      char **text = title ? &dc->title : &dc->description;
      *text = c_string(v);
      if (!*text) {
        xmp_dc_free(dc);
        return -1;
      }
    } else if (!p.structured) {
      subject.push_back(text_of(s, p.runs));
    } else {
      for (const Item &item : p.items) subject.push_back(text_of(s, item.runs));
    }
  }
  subject.erase(std::remove(subject.begin(), subject.end(), std::string()), subject.end());
  if (subject.empty()) return 0;
  dc->subject = static_cast<char **>(std::calloc(subject.size(), sizeof *dc->subject));
  if (!dc->subject) {
    xmp_dc_free(dc);
    return -1;
  }
  for (size_t k = 0; k < subject.size(); ++k) {
    dc->subject[k] = c_string(subject[k]);
    if (!dc->subject[k]) {
      xmp_dc_free(dc);
      return -1;
    }
    dc->num_subject = k + 1;
  }
  return 0;
}

extern "C" int xmp_set_dc(uint8_t **x, size_t *len, unsigned which, const char *title, const char *description,
                          const char *const *subject, size_t num_subject) {
  const std::string s(reinterpret_cast<const char *>(*x), *len);
  Layout layout;
  const std::vector<Property> props = scan(s, &layout);
  std::vector<Edit> edits;
  for (const Property &p : props) {
    if (((which & XMP_DC_TITLE) && is(p.name, DC, "dc", "title")) ||
        ((which & XMP_DC_DESCRIPTION) && is(p.name, DC, "dc", "description")) ||
        ((which & XMP_DC_SUBJECT) && is(p.name, DC, "dc", "subject")))
      edits.push_back(removal(s, p));
  }
  std::string body;
  const auto alternative = [&](const std::string &local, const char *value) {
    body += "  <dc:" + local + ">\n   <rdf:Alt>\n    <rdf:li xml:lang=\"x-default\">" + escaped(value) +
            "</rdf:li>\n   </rdf:Alt>\n  </dc:" + local + ">\n";
  };
  if ((which & XMP_DC_TITLE) && title && *title) alternative("title", title);
  if ((which & XMP_DC_DESCRIPTION) && description && *description) alternative("description", description);
  if ((which & XMP_DC_SUBJECT) && num_subject) {
    body += "  <dc:subject>\n   <rdf:Bag>\n";
    for (size_t k = 0; k < num_subject; ++k) body += "    <rdf:li>" + escaped(subject[k]) + "</rdf:li>\n";
    body += "   </rdf:Bag>\n  </dc:subject>\n";
  }
  if (!body.empty()) {
    if (layout.rdf_end == std::string::npos && layout.rdf_empty == std::string::npos) return -2;
    // The same rdf:about as the packet's other descriptions, as XMP requires.
    std::string about;
    for (const char c : layout.about) about += c == '"' ? std::string("&quot;") : std::string(1, c);
    const std::string node = "<rdf:Description rdf:about=\"" + about + "\" xmlns:rdf=\"" + RDF +
                             "\"\n   xmlns:dc=\"" + DC + "\">\n" + body + " </rdf:Description>\n";
    if (layout.rdf_end != std::string::npos) {
      Edit add = {layout.rdf_end, layout.rdf_end, node};
      edits.push_back(add);
    } else {
      // An empty rdf:RDF in one tag: its "/>" becomes ">", the node element
      // and its end tag, under the name it is written with.
      Edit add = {layout.rdf_empty, layout.rdf_empty + 2, ">" + node + "</" + layout.rdf_qualified + ">"};
      edits.push_back(add);
    }
  }
  return apply_edits(x, len, s, edits);
}

extern "C" int xmp_remove_location(uint8_t **x, size_t *len) {
  const std::string s(reinterpret_cast<const char *>(*x), *len);
  std::vector<Edit> edits;
  for (const Property &p : scan(s))
    if (is_location(p.name)) edits.push_back(removal(s, p));
  return apply_edits(x, len, s, edits);
}

extern "C" int xmp_new_packet(uint8_t **x, size_t *len) {
  static const char kPacket[] =
      "<?xpacket begin=\"\xEF\xBB\xBF\" id=\"W5M0MpCehiHzreSzNTczkc9d\"?>\n"
      "<x:xmpmeta xmlns:x=\"adobe:ns:meta/\">\n"
      " <rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\">\n"
      " </rdf:RDF>\n"
      "</x:xmpmeta>\n"
      "<?xpacket end=\"w\"?>";
  *x = static_cast<uint8_t *>(std::malloc(sizeof kPacket - 1));
  if (!*x) return -1;
  std::memcpy(*x, kPacket, sizeof kPacket - 1);
  *len = sizeof kPacket - 1;
  return 0;
}
