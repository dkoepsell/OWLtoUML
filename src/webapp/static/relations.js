/* Standard relations offered in edit mode's property dropdown.
 * BFO 2020 (ISO/IEC 21838-2) object properties, by their OBO IRIs.
 * Picking one that the ontology does not yet declare adds a declaration
 * (owl:ObjectProperty + rdfs:label) to the exported OWL.
 */
"use strict";
(function () {
  const B = "http://purl.obolibrary.org/obo/BFO_";
  const BFO = [
    ["0000050", "part of"], ["0000051", "has part"],
    ["0000176", "continuant part of"], ["0000178", "has continuant part"],
    ["0000132", "occurrent part of"], ["0000117", "has occurrent part"],
    ["0000139", "temporal part of"], ["0000121", "has temporal part"],
    ["0000056", "participates in"], ["0000057", "has participant"],
    ["0000197", "inheres in"], ["0000196", "bearer of"],
    ["0000195", "specifically depends on"], ["0000194", "specifically depended on by"],
    ["0000084", "generically depends on"], ["0000101", "is carrier of"],
    ["0000059", "concretizes"], ["0000058", "is concretized by"],
    ["0000055", "realizes"], ["0000054", "has realization"],
    ["0000218", "has material basis"], ["0000127", "material basis of"],
    ["0000171", "located in"], ["0000124", "location of"],
    ["0000066", "occurs in"], ["0000183", "environs"],
    ["0000062", "preceded by"], ["0000063", "precedes"],
    ["0000184", "history of"], ["0000185", "has history"],
    ["0000108", "exists at"],
    ["0000199", "occupies temporal region"], ["0000200", "occupies spatiotemporal region"],
    ["0000210", "occupies spatial region"],
    ["0000153", "temporally projects onto"], ["0000216", "spatially projects onto"],
    ["0000221", "first instant of"], ["0000222", "has first instant"],
    ["0000223", "last instant of"], ["0000224", "has last instant"],
  ].map(([n, label]) => ({ iri: B + n, label }));

  window.OwlUmlRelations = [{ group: "BFO 2020", items: BFO }];
})();
