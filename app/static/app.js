/* Production client: mission data comes only from the authenticated API. */
(() => {
  "use strict";
  const root = document.getElementById("lockin-mock"),
    q = (s) => root.querySelector(s);
  const demo = new URLSearchParams(location.search).has("demo");
  const demoApi = demo ? window.createLockinDemo() : null;
  const journalNodes = new Map();
  const terminal = new Set([
    "stopped",
    "completed",
    "budget_exhausted",
    "deadline_reached",
    "failed",
  ]);
  const names = {
    pending: "En attente",
    running: "Veille en cours",
    stopping: "Arrêt en cours",
    stopped: "Veille arrêtée",
    completed: "Veille terminée",
    budget_exhausted: "Budget épuisé",
    deadline_reached: "Durée limite atteinte",
    failed: "Veille interrompue",
  };
  const tools = {
    search_web: "Recherche de sources",
    read_page: "Lecture d’une source",
    save_finding: "Enregistrement d’un constat",
    finish: "Recherche terminée",
  };
  const eventNames = {
    created: "Mission créée",
    started: "Mission démarrée",
    model_started: "Appel à Haiku",
    model_finished: "Réponse de Haiku",
    network_started: "Requête réseau",
    action_reserved: "Action décomptée",
    action_started: "Action lancée",
    action_finished: "Action terminée",
    page_attempt: "Consultation de page",
    page_saved: "Source conservée",
    finding_saved: "Constat enregistré",
    tool_error: "Difficulté rencontrée",
    stop_requested: "Arrêt demandé",
    finished: "Mission terminée",
  };
  let domains = ["openai.com", "www.anthropic.com", "docs.langchain.com"];
  let mission = null,
    token = "",
    timer = null,
    generation = 0,
    launching = false,
    failures = 0;
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  };
  const time = (seconds) =>
    `${String(Math.floor(Math.max(0, seconds) / 60)).padStart(2, "0")}:${String(Math.floor(Math.max(0, seconds)) % 60).padStart(2, "0")}`;
  const date = (value) => {
    if (!value) return "Date inconnue";
    const d = new Date(value);
    return Number.isNaN(d.getTime())
      ? "Date inconnue"
      : d.toLocaleDateString("fr-FR");
  };
  function https(value) {
    try {
      const url = new URL(value);
      return url.protocol === "https:" && !url.username && !url.password
        ? url.href
        : null;
    } catch {
      return null;
    }
  }
  function link(label, url) {
    const safe = https(url);
    if (!safe) return el("span", "", label);
    const a = el("a", "", label);
    a.href = safe;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  }
  function notice(message) {
    q("#lk-notice").textContent = message;
    q("#lk-notice").hidden = !message;
  }
  function formError(message) {
    q("#lk-error").textContent = message;
    q("#lk-error").hidden = !message;
  }
  function remember(id) {
    try {
      if (id) sessionStorage.setItem("lockin-mission-id", id);
      else sessionStorage.removeItem("lockin-mission-id");
    } catch {}
  }
  function remembered() {
    try {
      return sessionStorage.getItem("lockin-mission-id");
    } catch {
      return null;
    }
  }
  function showWork() {
    q("#lk-home").hidden = true;
    q("#lk-work").hidden = false;
    q("#lk-nav").hidden = false;
  }
  function showTab(name) {
    for (const tab of ["results", "journal", "sources"])
      q("#lk-" + tab).hidden = tab !== name;
    root
      .querySelectorAll("[data-tab]")
      .forEach((b) =>
        b.setAttribute("aria-pressed", String(b.dataset.tab === name)),
      );
  }
  function drawDomains() {
    const host = q("#lk-domains");
    host.replaceChildren();
    domains.forEach((domain, index) => {
      const chip = el("span", "lk-domain");
      chip.append(el("span", "", domain));
      const remove = el("button", "", "×");
      remove.type = "button";
      remove.setAttribute("aria-label", "Retirer " + domain);
      remove.onclick = () => {
        domains.splice(index, 1);
        drawDomains();
      };
      chip.append(remove);
      host.append(chip);
    });
    if (domains.length < 5) {
      const add = el("button", "lk-add", "+ Domaine");
      add.type = "button";
      add.onclick = () => {
        q("#lk-domainentry").hidden = false;
        q("#lk-domaininput").focus();
      };
      host.append(add);
    }
    q("#lk-count").textContent = domains.length + " / 5 domaines";
  }
  q("#lk-confirmdomain").onclick = () => {
    const value = q("#lk-domaininput").value.trim().toLowerCase();
    if (
      !/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}$/.test(value) ||
      domains.includes(value) ||
      domains.length >= 5
    ) {
      formError("Indiquez un domaine distinct, sans https:// ni chemin.");
      return;
    }
    domains.push(value);
    q("#lk-domaininput").value = "";
    q("#lk-domainentry").hidden = true;
    formError("");
    drawDomains();
  };
  q("#lk-domaininput").onkeydown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      q("#lk-confirmdomain").click();
    }
  };
  function updateLimits() {
    for (const id of ["budget", "duration"]) {
      const number = q("#lk-" + id),
        range = q("#lk-" + id + "range");
      if (number.value !== "" && Number.isFinite(number.valueAsNumber))
        range.value = number.value;
      range.style.setProperty(
        "--lk-fill",
        ((Number(range.value) - Number(range.min)) /
          (Number(range.max) - Number(range.min))) *
          100 +
          "%",
      );
      range.setAttribute(
        "aria-valuetext",
        range.value + (id === "budget" ? " actions" : " minutes"),
      );
    }
    let name = "Personnalisé";
    root.querySelectorAll(".lk-pack").forEach((button) => {
      const active =
        Number(button.dataset.budget) === q("#lk-budget").valueAsNumber &&
        Number(button.dataset.duration) === q("#lk-duration").valueAsNumber;
      button.setAttribute("aria-pressed", String(active));
      if (active) name = button.dataset.name;
    });
    q("#lk-packstate").textContent = name;
  }
  for (const id of ["budget", "duration"]) {
    const number = q("#lk-" + id),
      range = q("#lk-" + id + "range");
    number.oninput = updateLimits;
    range.oninput = () => {
      number.value = range.value;
      updateLimits();
    };
  }
  root.querySelectorAll(".lk-pack").forEach(
    (button) =>
      (button.onclick = () => {
        q("#lk-budget").value = button.dataset.budget;
        q("#lk-duration").value = button.dataset.duration;
        updateLimits();
      }),
  );
  async function api(path, options = {}) {
    if (demo) return demoApi(path, options);
    const controller = new AbortController(),
      timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch("/api/" + path, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + token,
        },
        signal: controller.signal,
        cache: "no-store",
        credentials: "omit",
      });
      let data;
      try {
        data = await response.json();
      } catch {
        throw new Error(
          "Réponse du serveur illisible. Réessayez dans un instant.",
        );
      }
      if (!response.ok) {
        const messages = {
          401: "Code d’accès incorrect.",
          404: "Mission introuvable.",
          409: "Une autre mission est déjà en cours. Réessayez après sa fin.",
          422: "Sujet, sources ou limites invalides.",
          429: "Trop de requêtes. Réessayez dans un instant.",
          503: "Le service de recherche n’est pas encore configuré.",
        };
        const error = new Error(
          messages[response.status] ||
            "Le serveur est momentanément indisponible.",
        );
        error.status = response.status;
        throw error;
      }
      return data;
    } catch (error) {
      if (error.name === "AbortError")
        throw new Error(
          "Le serveur ne répond pas. La mission peut continuer en arrière-plan.",
        );
      if (error instanceof TypeError)
        throw new Error("Connexion au serveur indisponible.");
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }
  function eventText(event) {
    const d = event.data || {};
    if (d.code) return (tools[d.tool] || "Action") + " · " + d.code;
    if (d.result?.error)
      return (
        "#" +
        (d.action_number ?? "?") +
        " · " +
        (d.tool || "outil") +
        " · " +
        d.result.error
      );
    if (d.tool)
      return (
        (d.action_number ? "#" + d.action_number + " · " : "") +
        (tools[d.tool] || d.tool) +
        " (" +
        d.tool +
        ")"
      );
    if (d.proposed_action) return tools[d.proposed_action] || d.proposed_action;
    if (d.url) return d.url;
    if (d.status) return names[d.status] || d.status;
    if (d.request) return d.request.subject;
    if (d.source_id) return "Source " + d.source_id.slice(0, 8);
    return "";
  }
  function eventRow(event, state) {
    const row = el("div", "lk-logrow");
    row.dataset.kind = event.kind;
    const code = event.data?.result?.error || event.data?.code;
    const failureLabel =
      code === "cancelled"
        ? "Appel interrompu"
        : /^(tool_disabled|blocked_|invalid_|unknown_tool)/.test(code || "")
          ? "Appel refusé"
          : "Échec d’outil";
    row.append(
      el(
        "time",
        "",
        time((new Date(event.at) - new Date(state.created_at)) / 1000),
      ),
      el(
        "strong",
        "",
        code ? failureLabel : eventNames[event.kind] || event.kind,
      ),
    );
    const body = el("div", "lk-logbody");
    body.append(el("p", "", eventText(event)));
    const d = event.data || {};
    if (d.parameters !== undefined || d.result !== undefined) {
      const details = el("details", "");
      details.open = true;
      details.append(
        el(
          "summary",
          "",
          d.parameters !== undefined ? "Arguments envoyés" : "Résultat reçu",
        ),
      );
      details.append(
        el("pre", "", JSON.stringify(d.parameters ?? d.result, null, 2)),
      );
      body.append(details);
    }
    row.append(body);
    return row;
  }
  function render(state) {
    if (mission?.id !== state.id) {
      journalNodes.clear();
      q("#lk-events").replaceChildren();
    }
    mission = state;
    if (!demo) remember(state.id);
    showWork();
    const done = terminal.has(state.status);
    q("#lk-nav").disabled = !done;
    q("#lk-nav").textContent = done ? "Nouvelle veille" : "Mission en cours";
    q("#lk-status").textContent = names[state.status] || state.status;
    q("#lk-missiontitle").textContent = state.subject;
    q("#lk-missionsub").textContent =
      "7 derniers jours · " + state.domains.length + " domaines autorisés";
    q("#lk-stop").hidden = done;
    q("#lk-stop").disabled = state.status === "stopping";
    q("#lk-stop span").textContent =
      state.status === "stopping" ? "Arrêt demandé" : "Arrêter la veille";
    q("#lk-used").textContent = state.actions_used;
    q("#lk-total").textContent = "sur " + state.action_budget;
    q("#lk-remaining").textContent = state.actions_remaining + " restantes";
    q("#lk-elapsed").textContent = time(state.elapsed_seconds);
    q("#lk-timemax").textContent =
      "sur " + Math.round(state.duration_seconds / 60) + " min";
    q("#lk-budgetarc").setAttribute(
      "stroke-dasharray",
      Math.min(1, state.actions_used / state.action_budget) * 270.18 +
        " 270.18",
    );
    q("#lk-timearc").setAttribute(
      "stroke-dasharray",
      Math.min(1, state.elapsed_seconds / state.duration_seconds) * 270.18 +
        " 270.18",
    );
    q("#lk-currentlabel").textContent = done
      ? "MISSION CLOSE"
      : state.status === "stopping"
        ? "ARRÊT DEMANDÉ"
        : "ACTION EN COURS";
    q("#lk-currenttext").textContent = done
      ? names[state.status] || state.status
      : state.status === "stopping"
        ? "Arrêt de l’appel en cours"
        : tools[state.current_action] || "Haiku prépare la prochaine action";
    q("#lk-currentdomain").textContent =
      state.model_calls_used +
      " appels modèle · " +
      state.network_requests_used +
      " requêtes réseau";
    if (state.error)
      notice(
        "La mission s’est interrompue : " +
          state.error +
          ". Les résultats déjà obtenus sont conservés.",
      );
    q("#lk-findingcount").textContent = state.findings.length;
    q("#lk-reportlabel").textContent = done
      ? state.summary.partial
        ? "SYNTHÈSE PARTIELLE"
        : "SYNTHÈSE TERMINÉE"
      : "SYNTHÈSE EN CONSTRUCTION";
    const results = q("#lk-findings");
    results.replaceChildren();
    for (const finding of state.findings) {
      const article = el("article", "lk-result");
      const sources = el("div", "lk-source");
      for (const evidence of finding.evidence) {
        const source = state.sources.find(
          (s) => s.source_id === evidence.source_id,
        );
        if (source && https(source.url))
          sources.append(link(new URL(source.url).hostname, source.url));
      }
      sources.append(
        el(
          "span",
          "",
          finding.date_status === "unknown"
            ? "Date de publication inconnue"
            : date(finding.event_date) +
                (finding.date_status === "outside_window"
                  ? " · Hors des 7 derniers jours"
                  : ""),
        ),
      );
      article.append(
        sources,
        el("h3", "", finding.title),
        el("p", "", finding.summary),
        el("div", "lk-interest", finding.developer_impact),
      );
      for (const caveat of finding.caveats || [])
        article.append(el("div", "lk-caveat", caveat));
      const details = el("details", "lk-caveat");
      details.append(el("summary", "", "Voir les extraits cités"));
      for (const evidence of finding.evidence)
        details.append(el("blockquote", "", evidence.quote));
      article.append(details);
      results.append(article);
    }
    if (!state.findings.length)
      results.append(
        el(
          "p",
          "lk-empty",
          done
            ? "Aucun résultat exploitable trouvé pour cette mission."
            : "Recherche en cours. Les constats apparaîtront après lecture et vérification des sources.",
        ),
      );
    const sourceHost = q("#lk-sources");
    sourceHost.replaceChildren();
    for (const source of state.sources) {
      const row = el("div", "lk-sourcerow");
      row.append(
        link(source.title || source.url, source.url),
        el(
          "small",
          "",
          source.status === "ok"
            ? "Consultée le " + date(source.retrieved_at)
            : "Non consultée · " + (source.error || "indisponible"),
        ),
      );
      sourceHost.append(row);
    }
    if (!state.sources.length)
      sourceHost.append(
        el("p", "lk-empty", "Aucune source consultée pour le moment."),
      );
    const journal = q("#lk-events"),
      recent = q("#lk-recent");
    recent.replaceChildren();
    const events = [...state.events].reverse();
    for (const event of [...state.events].sort((a, b) => a.seq - b.seq)) {
      if (!journalNodes.has(event.seq)) {
        const row = eventRow(event, state);
        journalNodes.set(event.seq, row);
        journal.prepend(row);
      }
    }
    const lastError = events.find((e) => e.kind === "tool_error");
    q("#lk-tool-warning").hidden = !lastError;
    if (lastError)
      q("#lk-tool-warning").textContent =
        "Dernier incident : " +
        eventText(lastError) +
        ". Les résultats déjà enregistrés restent disponibles.";
    for (const event of events
      .filter(
        (e) =>
          !["network_started", "action_reserved", "model_started"].includes(
            e.kind,
          ),
      )
      .slice(0, 3)) {
      const row = el("div", "lk-event");
      row.append(
        el(
          "time",
          "",
          time((new Date(event.at) - new Date(state.created_at)) / 1000),
        ),
        el("strong", "", eventNames[event.kind] || event.kind),
        el("p", "", eventText(event)),
      );
      recent.append(row);
    }
  }
  async function poll(id, version) {
    if (version !== generation) return;
    try {
      const state = await api("missions/" + encodeURIComponent(id));
      if (version !== generation) return;
      failures = 0;
      notice("");
      q("#lk-reconnect").hidden = true;
      render(state);
      q("#lk-connection").textContent = demo
        ? "Simulation locale · Aucun appel API"
        : "Dernière réception : " +
          new Date().toLocaleTimeString("fr-FR") +
          " · Actualisation chaque seconde";
      if (terminal.has(state.status)) return;
    } catch (error) {
      if (version !== generation) return;
      failures++;
      notice(
        error.message + " Les données affichées sont les dernières reçues.",
      );
      q("#lk-connection").textContent =
        "Suivi interrompu · État de la mission à confirmer";
      q("#lk-reconnect").hidden = false;
      if (error.status === 401 || error.status === 404) return;
    }
    timer = setTimeout(
      () => poll(id, version),
      Math.min(10000, 1000 * Math.max(1, failures)),
    );
  }
  q("#lk-form").onsubmit = (e) => e.preventDefault();
  q(".lk-submit").onclick = async () => {
    if (launching || !q("#lk-form").reportValidity()) return;
    if (!domains.length) {
      formError("Ajoutez au moins un domaine autorisé.");
      return;
    }
    launching = true;
    q(".lk-submit").disabled = true;
    formError("");
    token = q("#lk-access").value.trim();
    try {
      const config = await api("config");
      if (!config.provider_ready)
        throw new Error(
          "La clé Anthropic n’est pas configurée sur le serveur.",
        );
      const previous = demo ? null : remembered();
      let state;
      if (previous) {
        try {
          state = await api("missions/" + encodeURIComponent(previous));
        } catch (error) {
          if (error.status !== 404) throw error;
          remember(null);
        }
      }
      if (!state)
        state = await api("missions", {
          method: "POST",
          body: JSON.stringify({
            subject: q("#lk-topic").value.trim(),
            domains,
            action_budget: Number(q("#lk-budget").value),
            duration_minutes: Number(q("#lk-duration").value),
          }),
        });
      q("#lk-access").value = "";
      clearTimeout(timer);
      generation++;
      failures = 0;
      notice("");
      showTab("results");
      render(state);
      if (!terminal.has(state.status))
        timer = setTimeout(() => poll(state.id, generation), 1000);
    } catch (error) {
      formError(error.message);
    } finally {
      launching = false;
      q(".lk-submit").disabled = false;
    }
  };
  q("#lk-stop").onclick = async () => {
    if (!mission || terminal.has(mission.status)) return;
    q("#lk-stop").disabled = true;
    try {
      const state = await api(
        "missions/" + encodeURIComponent(mission.id) + "/stop",
        { method: "POST" },
      );
      notice("");
      clearTimeout(timer);
      generation++;
      render(state);
      if (!terminal.has(state.status))
        timer = setTimeout(() => poll(state.id, generation), 500);
    } catch (error) {
      notice(error.message + " L’arrêt n’est pas confirmé.");
      q("#lk-stop").disabled = false;
    }
  };
  q("#lk-nav").onclick = () => {
    if (mission && !terminal.has(mission.status)) return;
    clearTimeout(timer);
    generation++;
    mission = null;
    remember(null);
    q("#lk-home").hidden = false;
    q("#lk-work").hidden = true;
    q("#lk-nav").hidden = true;
    q("#lk-access").value = token;
    q(".lk-submit").textContent = "Lancer la veille";
    notice("");
  };
  root
    .querySelectorAll("[data-tab]")
    .forEach((button) => (button.onclick = () => showTab(button.dataset.tab)));
  q("#lk-reconnect").onclick = () => {
    clearTimeout(timer);
    generation++;
    q("#lk-home").hidden = false;
    q("#lk-work").hidden = true;
    q("#lk-access").value = "";
    q(".lk-submit").textContent = "Retrouver ma veille";
    q("#lk-access").focus();
  };
  q("#lk-export").onclick = () => {
    if (!mission) return;
    const blob = new Blob(
      [
        JSON.stringify(
          {
            mission_id: mission.id,
            subject: mission.subject,
            simulated: demo,
            events: mission.events,
          },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob);
    const a = el("a");
    a.href = url;
    a.download = "lockin-journal-" + mission.id + ".json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  if (!demo && remembered()) {
    q(".lk-submit").textContent = "Retrouver ma veille";
    q("#lk-accesshelp").textContent =
      "Saisissez votre code pour retrouver la dernière mission de cet onglet.";
  }
  if (demo) {
    q("#lk-demo-banner").hidden = false;
    q("#lk-auth").hidden = true;
    q("#lk-access").required = false;
    q("#lk-demo-options").hidden = false;
    q(".lk-proto").textContent = "DÉMONSTRATION";
    q("#lk-connection").textContent = "Simulation locale · Aucun appel API";
  }
  drawDomains();
  updateLimits();
  if (window.lucide)
    window.lucide.createIcons({ attrs: { width: 16, height: 16 } });
})();
