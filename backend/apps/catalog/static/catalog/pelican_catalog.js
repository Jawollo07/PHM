(function () {
  "use strict";
  const root = document.getElementById("pelican-catalog-helper");
  if (!root) return;
  const url = root.dataset.url;
  const byId = (id) => document.getElementById(id);
  const node = byId("pelican-node");
  const nest = byId("pelican-nest");
  const egg = byId("pelican-egg");
  const allocation = byId("pelican-allocation");
  const controls = byId("pelican-catalog-controls");
  const status = byId("pelican-catalog-status");
  const apply = byId("pelican-apply-config");
  const resourceField = byId("id_resource_limits");
  let selectedEgg = null;
  let eggData = [];
  function setStatus(message, error) {
    status.textContent = message;
    status.style.color = error ? "#ba2121" : "";
  }
  function fill(select, items, placeholder, label) {
    select.replaceChildren(new Option(placeholder, ""));
    items.forEach((item) => select.add(new Option(label(item), String(item.id))));
  }
  async function request(params) {
    const target = new URL(url, window.location.origin);
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") target.searchParams.set(key, value);
    });
    const response = await fetch(target, { credentials: "same-origin", headers: { Accept: "application/json" } });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Panel-Katalog konnte nicht geladen werden.");
    return payload;
  }
  function updateApply() {
    apply.disabled = !(selectedEgg && allocation.value);
  }
  byId("pelican-load-catalog").addEventListener("click", async () => {
    setStatus("Verbinde mit Pelican …");
    try {
      const data = await request({});
      fill(node, data.nodes, "Node auswählen …", (item) => item.name + " (#" + item.id + ")");
      fill(nest, data.nests, "Nest auswählen …", (item) => item.name + " (#" + item.id + ")");
      controls.hidden = false;
      setStatus(data.nodes.length + " Nodes und " + data.nests.length + " Nests geladen.");
    } catch (error) { setStatus(error.message, true); }
  });
  node.addEventListener("change", async () => {
    fill(allocation, [], "Allocation auswählen …", (item) => item.alias);
    updateApply();
    if (!node.value) return;
    setStatus("Lade freie Allocations …");
    try {
      const data = await request({ node_id: node.value });
      fill(allocation, data.allocations, "Allocation auswählen …", (item) => {
        const address = item.ip_alias || item.ip;
        return address + ":" + item.port + (item.notes ? " – " + item.notes : "");
      });
      setStatus(data.allocations.length + " freie Allocations geladen.");
    } catch (error) { setStatus(error.message, true); }
  });
  nest.addEventListener("change", async () => {
    fill(egg, [], "Egg auswählen …", (item) => item.name);
    selectedEgg = null;
    eggData = [];
    updateApply();
    if (!nest.value) return;
    setStatus("Lade Eggs und Environment-Variablen …");
    try {
      const data = await request({ nest_id: nest.value });
      eggData = data.eggs;
      fill(egg, eggData, "Egg auswählen …", (item) => item.name + " (#" + item.id + ")");
      setStatus(data.eggs.length + " Eggs geladen.");
    } catch (error) { setStatus(error.message, true); }
  });
  egg.addEventListener("change", () => {
    selectedEgg = eggData.find((item) => String(item.id) === egg.value) || null;
    updateApply();
  });
  apply.addEventListener("click", () => {
    if (!selectedEgg || !allocation.value || !resourceField) return;
    let current = {};
    try {
      current = resourceField.value.trim() ? JSON.parse(resourceField.value) : {};
      if (!current || typeof current !== "object" || Array.isArray(current)) current = {};
    } catch (_error) {
      setStatus("Das vorhandene Ressourcen-JSON ist ungültig. Bitte zuerst korrigieren oder leeren.", true);
      return;
    }
    const environment = {};
    (selectedEgg.variables || []).forEach((variable) => {
      if (variable.env_variable) environment[variable.env_variable] = variable.default_value ?? "";
    });
    const previous = current.pelican || {};
    current.pelican = {
      ...previous,
      egg_id: selectedEgg.id,
      allocation_id: Number(allocation.value),
      docker_image: selectedEgg.docker_image || "",
      startup: selectedEgg.startup || "",
      environment: { ...(previous.environment || {}), ...environment },
      limits: previous.limits || { memory: 4096, swap: 0, disk: 20480, io: 500, cpu: 200 },
      feature_limits: previous.feature_limits || { databases: 1, allocations: 1, backups: 2 },
      skip_scripts: previous.skip_scripts ?? false,
      oom_disabled: previous.oom_disabled ?? false,
      start_on_completion: previous.start_on_completion ?? true
    };
    resourceField.value = JSON.stringify(current, null, 2);
    resourceField.dispatchEvent(new Event("input", { bubbles: true }));
    resourceField.dispatchEvent(new Event("change", { bubbles: true }));
    setStatus("Konfiguration übernommen. Bitte Limits und Environment prüfen und den Tarif speichern.");
  });
})();
