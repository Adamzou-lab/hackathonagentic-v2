/* Production client: mission data comes only from the authenticated API. */
(() => {
  "use strict";
  const root = document.getElementById("lockin-mock"),
    q = (s) => root.querySelector(s);
  const demo = new URLSearchParams(location.search).has("demo");
  const apiBase = document.querySelector('meta[name="lockin-api-base"]')?.content || "";
  const demoApi = demo ? window.createLockinDemo() : null;
  const journalNodes = new Map();
  // Incidents constates par le navigateur. Volontairement separes des
  // evenements du serveur : ils n'ont pas de seq, ils ne font pas foi, et
  // leur horodatage est une heure de detection, pas une heure de panne.
  const incidents = [];
  let connecte = true;
  function majSituation() {
    const vue = window.LockinJournal.situation(
      mission ? mission.status : null,
      connecte,
    );
    const noeud = q("#lk-situation");
    if (!noeud) return;
    noeud.dataset.severity = vue.severity;
    noeud.dataset.source = vue.source;
    noeud.replaceChildren(el("strong", "", vue.label), el("span", "", vue.detail));
    noeud.hidden = vue.key === "running";
  }
  function signaler(kind, detail) {
    const J = window.LockinJournal;
    const item = J.incident(kind, detail);
    incidents.push(item);
    const ligne = el("div", "lk-logrow lk-incident");
    ligne.dataset.kind = "client_" + kind;
    const horloge = el("time", "lk-stamp");
    horloge.dateTime = item.detected_at;
    horloge.append(
      el("span", "lk-elapsed", "navigateur"),
      el("span", "lk-abs", J.stamp(item.detected_at).absolute),
    );
    const corps = el("div", "lk-logbody");
    corps.append(el("p", "", item.detail || kind));
    corps.append(el("p", "lk-incident-note", item.note));
    ligne.append(horloge, el("strong", "", "Incident de connexion"), corps);
    q("#lk-events").prepend(ligne);
    majSituation();
    return item;
  }
  const terminal = new Set([
    "refused",
    "stopped",
    "completed",
    "budget_exhausted",
    "deadline_reached",
    "failed",
  ]);
  const names = {
    refused: "Demande refusée",
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
    discover_sources: "Découverte des sources",
    select_sources: "Sélection des domaines",
  };
  const eventNames = {
    operation_started: "Appel externe commencé",
    operation_finished: "Appel externe terminé",
    dependency_failed: "Panne détectée",
    heartbeat: "Signe de vie du moteur",
    recovery_detected: "Interruption constatée au redémarrage",
    scope_accepted: "Périmètre validé",
    mission_refused: "Demande refusée",
    created: "Mission créée",
    started: "Mission démarrée",
    model_started: "Appel à Haiku",
    model_finished: "Réponse de Haiku",
    finalization_started: "Finalisation de la synthèse",
    finalization_without_evidence: "Aucune preuve exploitable",
    finalization_tool_blocked: "Réserve de finalisation protégée",
    finding_target_reached: "Objectif de la veille atteint",
    token_budget_exhausted: "Seuil de tokens atteint",
    network_started: "Requête réseau",
    action_reserved: "Action décomptée",
    action_started: "Action lancée",
    action_finished: "Action terminée",
    page_attempt: "Consultation de page",
    page_saved: "Source conservée",
    finding_saved: "Constat enregistré",
    finding_updated: "Constat actualisé",
    finding_unchanged: "Information déjà connue",
    sources_selected: "Domaines sélectionnés",
    source_discovery_started: "Découverte des domaines démarrée",
    enrichment_prepared: "Actualisation préparée",
    tool_error: "Difficulté rencontrée",
    stop_requested: "Arrêt demandé",
    finished: "Mission terminée",
  };
  let domains = ["openai.com", "www.anthropic.com", "docs.langchain.com"];
  let publicAccess = false;
  let mission = null,
    token = "",
    timer = null,
    generation = 0,
    launching = false,
    failures = 0;
  let view = "home",
    libraryGeneration = 0,
    selectedWatch = null,
    pendingRequest = null;
  let resumePending = false;
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
  const findingDate = (finding) =>
    !finding.event_date || finding.date_status === "unknown"
      ? "Date de publication inconnue"
      : date(finding.event_date) +
        (finding.date_status === "outside_window"
          ? " · Hors période de recherche"
          : "");
  const confidenceLabel = (finding) =>
    ({
      single_source: "Une seule source",
      corroborated: "Information corroborée",
      conflicting: "Sources contradictoires",
    })[finding.confidence] || "Niveau de corroboration non précisé";
  const integer = (value) =>
    new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 }).format(
      Number(value) || 0,
    );
  const dollars = (value) =>
    new Intl.NumberFormat("fr-FR", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 4,
      maximumFractionDigits: 6,
    }).format(value);
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
    view = "work";
    q("#lk-home").hidden = true;
    q("#lk-library").hidden = true;
    q("#lk-work").hidden = false;
    q("#lk-nav").hidden = false;
  }
  function pauseFollow() {
    clearTimeout(timer);
    generation++;
    closeStream();
  }
  function newWatch() {
    pauseFollow();
    libraryGeneration++;
    view = "home";
    mission = null;
    selectedWatch = null;
    resumePending = false;
    remember(null);
    q("#lk-home").hidden = false;
    q("#lk-library").hidden = true;
    q("#lk-work").hidden = true;
    q("#lk-nav").hidden = true;
    q("#lk-access").value = token;
    q(".lk-submit").textContent = "Lancer la veille";
    q("#lk-similar").hidden = true;
    formError("");
    notice("");
    q("#lk-home").scrollIntoView({ block: "start" });
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
    const count = q("#lk-budget").valueAsNumber;
    const automatic = q("#lk-source-mode").value === "auto";
    const reserved = Math.min(3, Math.max(1, Math.floor(count / 4)), Math.max(0, count - (automatic ? 3 : 1)));
    q("#lk-budget-help").textContent = reserved
      ? `${count} actions au total, dont ${reserved} réservée(s) à la finalisation. Les recherches s’arrêtent avant de consommer cette réserve.`
      : "Budget trop court pour réserver une finalisation. Privilégiez le pack Rapide pour obtenir des constats.";
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
      const response = await fetch(apiBase + "/api/" + path, {
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
          (data.detail?.code === "api_disabled" ? data.detail.message : messages[response.status]) ||
            "Le serveur est momentanément indisponible.",
        );
        error.status = response.status;
        error.detail = data.detail;
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
    if (event.kind === "finalization_started")
      return "Finalisation : nouvelles recherches arrêtées, sauvegarde des preuves disponibles (" + ({actions:"réserve d’actions",tokens:"seuil de tokens",time:"temps restant"}[d.reason] || d.reason) + ").";
    if (event.kind === "finalization_without_evidence") return "Aucune page exploitable lue : aucun constat inventé.";
    if (event.kind === "finalization_tool_blocked") return "Nouvelle recherche bloquée pour préserver la finalisation.";
    if (event.kind === "recovery_detected")
      return "Dernier signe de vie : " + window.LockinJournal.stamp(d.last_seen_at).absolute + ". Heure exacte de coupure inconnue. Aucune relance automatique.";
    if (d.operation) return d.operation + (d.code ? " · " + d.code : "") + (d.outcome ? " · " + d.outcome : "");
    if (d.reason) return d.reason;
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
    if (d.status)
      return (
        (names[d.status] || d.status) +
        (d.error ? " · " + d.error : "")
      );
    if (d.request) return d.request.subject;
    if (d.source_id) return "Source " + d.source_id.slice(0, 8);
    if (d.domains) return d.domains.join(", ");
    if (d.sources)
      return d.sources
        .map((source) => source.domain)
        .filter(Boolean)
        .join(" · ");
    if (d.query) return d.query;
    if (d.known_findings_count !== undefined)
      return `${d.known_findings_count} constat(s) déjà connus transmis au modèle${d.known_findings_truncated ? " · résumé limité" : ""}`;
    return "";
  }
  function eventRow(event, state) {
    const row = el("div", "lk-logrow");
    row.dataset.kind = event.kind;
    const code = window.LockinJournal.failureCode(event);
    const failureLabel =
      code === "cancelled"
        ? "Appel interrompu"
        : /^(tool_disabled|blocked_|invalid_|unknown_tool)/.test(code || "")
          ? "Appel refusé"
          : "Échec d’outil";
    const J = window.LockinJournal;
    const marque = J.stamp(event.at);
    const ecoule = J.elapsed(event.at, state.created_at);
    const horloge = el("time", "lk-stamp");
    horloge.dateTime = marque.iso;
    // Le temps ecoule reste en tete, l'horodatage absolu le complete sans le
    // remplacer : l'un sert a suivre le rythme, l'autre a dater une panne.
    horloge.append(
      el("span", "lk-elapsed", ecoule === null ? "--" : time(ecoule)),
      el("span", "lk-abs", marque.absolute),
    );
    row.append(
      horloge,
      el(
        "strong",
        "",
        eventNames[event.kind] || (code ? failureLabel : event.kind),
      ),
    );
    const body = el("div", "lk-logbody");
    body.append(el("p", "", eventText(event)));
    const d = event.data || {};
    const panne = J.diagnoseEvent(event);
    if (panne) {
      const bloc = el("dl", "lk-diag" + (panne.known ? "" : " lk-diag-inconnu"));
      bloc.append(
        el("dt", "", "Dependance concernee"), el("dd", "", panne.dependency),
        el("dt", "", "Cause"), el("dd", "", panne.cause),
        el("dt", "", "Reaction de l'agent"), el("dd", "", panne.reaction),
      );
      body.append(bloc);
    }
    if (d.parameters !== undefined || d.result !== undefined || d.operation || d.reaction) {
      const details = el("details", "");
      details.open = true;
      details.append(
        el(
          "summary",
          "",
          d.parameters !== undefined ? "Arguments envoyés" : d.result !== undefined ? "Résultat reçu" : "Détails de l’événement",
        ),
      );
      details.append(
        el("pre", "", JSON.stringify(d.parameters ?? d.result ?? d, null, 2)),
      );
      body.append(details);
    }
    row.append(body);
    return row;
  }
  function render(state) {
    // Polling/SSE snapshots omit the reuse receipt returned by mission creation.
    if (mission?.id === state.id && mission.reuse && !state.reuse)
      state = { ...state, reuse: mission.reuse };
    if (mission?.id !== state.id) {
      journalNodes.clear();
      q("#lk-draft").hidden = true;
      q("#lk-draft-input").textContent = "";
      q("#lk-draft-text").textContent = "";
      q("#lk-events").replaceChildren();
    }
    mission = state;
    const usage = window.LockinUsage.presentation(state, demo);
    q("#lk-usage-tokens").textContent = usage.tokens;
    q("#lk-usage-calls").textContent = usage.calls;
    q("#lk-usage-duration").textContent = usage.duration;
    q("#lk-usage-note").textContent = usage.note;
    if (!demo) remember(state.id);
    showWork();
    const done = terminal.has(state.status);
    const early = q("#lk-early-summary");
    const advance = Math.max(0, state.duration_seconds - state.elapsed_seconds);
    const showEarly = ["completed", "budget_exhausted"].includes(state.status) && state.findings.length > 0 && advance > 0;
    early.hidden = !showEarly;
    if (showEarly) {
      early.textContent = (state.summary.partial ? "Synthèse partielle disponible" : "Synthèse prête") +
        " · terminée " + time(advance) + " avant la fin prévue. Votre synthèse est disponible dès maintenant.";
      if (early.dataset.mission !== state.id) {
        early.dataset.mission = state.id;
        early.classList.remove("lk-early-reveal");
        requestAnimationFrame(() => early.classList.add("lk-early-reveal"));
      }
    }
    q("#lk-nav").disabled = !done;
    q("#lk-nav").textContent = done ? "Nouvelle veille" : "Mission en cours";
    q("#lk-status").textContent = names[state.status] || state.status;
    majSituation();
    q("#lk-missiontitle").textContent = state.subject;
    q("#lk-missionsub").textContent =
      (state.update_since
        ? "Actualisation depuis le " + watchDate(state.update_since)
        : "7 derniers jours") +
      " · " +
      (state.domains.length
        ? state.domains.join(" · ")
        : state.auto_sources
          ? "Sélection automatique des sources en cours"
          : "Aucun domaine");
    q("#lk-mission-watch").hidden = !state.watch_id;
    q("#lk-enrichment").textContent =
      done && state.watch_id && state.status !== "refused"
        ? `${state.new_findings_count || 0} nouveauté(s) ajoutée(s) · ${state.updated_findings_count || 0} constat(s) actualisé(s)`
        : "";
    q("#lk-stop").hidden = done;
    q("#lk-stop").disabled = state.status === "stopping";
    q("#lk-stop span").textContent =
      state.status === "stopping" ? "Arrêt demandé" : "Arrêter la veille";
    q("#lk-used").textContent = state.actions_used;
    q("#lk-total").textContent = "sur " + state.action_budget;
    q("#lk-remaining").textContent = state.actions_remaining + " restantes";
    if (state.finalization_reason && !done)
      q("#lk-remaining").textContent += " · finalisation";
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
      ? "RECHERCHE TERMINÉE"
      : state.status === "stopping"
        ? "ARRÊT DEMANDÉ"
        : "EN COURS";
    q("#lk-currenttext").textContent = done
      ? names[state.status] || state.status
      : state.status === "stopping"
        ? "Arrêt de l’appel en cours"
        : tools[state.current_action] || "Lockin prépare votre recherche";
    q("#lk-currentdomain").textContent =
      state.model_calls_used +
      " appels modèle · " +
      state.network_requests_used +
      " requêtes réseau";
    const totalCost = state.total_estimated_cost_usd;
    q("#lk-publiccost").textContent = demo ? "Démo gratuite"
      : Number.isFinite(totalCost) && state.last_request_cost
        ? "≈ " + dollars(totalCost) : "—";
    q("#lk-publiccost-note").textContent = demo ? "Aucune dépense réelle"
      : !state.last_request_cost ? "Pas encore de coût mesuré"
      : !state.usage?.tokens_complete || !Number.isFinite(state.last_request_cost.amount_usd)
        ? "Estimation partielle · mesures manquantes"
        : "Estimation en dollars · appels terminés";
    const cost = state.last_request_cost;
    if (!cost) {
      q("#lk-lastcost").textContent = "—";
      q("#lk-lastcostdetail").textContent = "Aucun appel terminé";
    } else {
      q("#lk-lastcost").textContent = Number.isFinite(cost.amount_usd)
        ? "≈ " + dollars(cost.amount_usd)
        : "Indisponible";
      const details = [
        integer(cost.input_tokens) + " jetons entrée",
        integer(cost.output_tokens) + " sortie",
      ];
      if (cost.cache_creation_input_tokens)
        details.push(integer(cost.cache_creation_input_tokens) + " cache écrit");
      if (cost.cache_read_input_tokens)
        details.push(integer(cost.cache_read_input_tokens) + " cache lu");
      if (cost.web_search_requests)
        details.push(
          integer(cost.web_search_requests) +
            (cost.web_search_requests === 1
              ? " recherche web"
              : " recherches web"),
        );
      q("#lk-lastcostdetail").textContent =
        details.join(" · ") +
        (Number.isFinite(cost.amount_usd)
          ? " · estimation tarif public"
          : " · tarif du modèle non configuré");
    }
    if (state.status === "refused") notice(state.refusal_reason);
    else if (state.error)
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
    results.append(briefOverview(state.findings));
    results.append(el("h3", "lk-brief-heading", "02 · Les faits et leur portée"));
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
      sources.append(el("span", "", findingDate(finding)));
      article.append(
        sources,
        el("h3", "", finding.title),
        ...briefFinding(finding),
        el("div", "lk-caveat", confidenceLabel(finding)),
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
            ? state.summary?.text || "Aucun constat validé. Consultez le journal de la mission."
            : "Recherche en cours. Les constats apparaîtront après lecture et vérification des sources.",
        ),
      );
    results.append(briefLimits(state.findings, state.summary.partial));
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
  let streamController = null;
  function closeStream() {
    streamController?.abort();
    streamController = null;
  }
  async function follow(id, version) {
    if (demo) return poll(id, version);
    if (version !== generation) return;
    closeStream();
    const controller = new AbortController();
    streamController = controller;
    let lastSeq = Math.max(0, ...(mission?.events || []).map((e) => e.seq)),
      ended = false,
      refreshTimer = null,
      refreshing = false,
      idle;
    const activity = () => {
      clearTimeout(idle);
      idle = setTimeout(() => controller.abort(), 45000);
    };
    const refresh = async () => {
      if (refreshing || version !== generation) return;
      refreshing = true;
      try {
        const state = await api("missions/" + encodeURIComponent(id));
        if (version === generation && !ended) render(state);
      } catch {
        if (version === generation)
          notice(
            "Actualisation de l’état indisponible. Le journal reçu reste visible.",
          );
      } finally {
        refreshing = false;
      }
    };
    try {
      activity();
      const response = await fetch(
        apiBase + "/api/missions/" + encodeURIComponent(id) + "/stream",
        {
          headers: {
            Authorization: "Bearer " + token,
            "Last-Event-ID": String(lastSeq),
          },
          signal: controller.signal,
          cache: "no-store",
          credentials: "omit",
        },
      );
      if (response.status === 404) {
        q("#lk-connection").textContent =
          "Flux indisponible · Actualisation chaque seconde";
        return poll(id, version);
      }
      if (!response.ok)
        throw new Error(
          response.status === 401
            ? "Code d’accès expiré ou incorrect."
            : "Flux momentanément indisponible.",
        );
      if (!response.headers.get("content-type")?.includes("text/event-stream"))
        throw new Error("Format de flux inattendu.");
      q("#lk-connection").textContent =
        "Flux connecté · Événements reçus en direct";
      q("#lk-reconnect").hidden = true;
      if (!connecte) signaler("flux_retabli", "Le flux a été rétabli.");
      failures = 0;
      connecte = true;
      majSituation();
      notice("");
      await window.readLockinStream(
        response,
        async (kind, data) => {
          if (version !== generation) return false;
          if (data?.mission_id !== id) return;
          if (kind === "journal") {
            if (!Number.isInteger(data.seq) || data.seq <= lastSeq) return;
            lastSeq = data.seq;
            if (!journalNodes.has(data.seq)) {
              const row = eventRow(data, mission);
              journalNodes.set(data.seq, row);
              q("#lk-events").prepend(row);
            }
            if (!mission.events.some((e) => e.seq === data.seq))
              mission.events.push(data);
            if (data.kind === "model_started") {
              q("#lk-draft").hidden = true;
              q("#lk-draft-input").textContent = "";
              q("#lk-draft-text").textContent = "";
            }
            clearTimeout(refreshTimer);
            refreshTimer = setTimeout(refresh, 100);
          } else if (kind === "draft") {
            q("#lk-draft").hidden = false;
            if (data.phase === "tool_input_started") {
              q("#lk-draft-action").textContent =
                "Appel proposé : " + (data.action || "outil");
              q("#lk-draft-input").textContent = "";
            }
            if (data.phase === "tool_input")
              q("#lk-draft-input").textContent = (
                q("#lk-draft-input").textContent + (data.partial_json || "")
              ).slice(-16000);
            if (data.phase === "text")
              q("#lk-draft-text").textContent = (
                q("#lk-draft-text").textContent + (data.text || "")
              ).slice(-16000);
          } else if (kind === "end") {
            const state = await api("missions/" + encodeURIComponent(id));
            if (version !== generation) return false;
            render(state);
            ended = true;
            q("#lk-connection").textContent = "Flux terminé · Journal conservé";
            return false;
          }
        },
        activity,
      );
      if (!ended && version === generation)
        throw new Error("Connexion au flux interrompue.");
    } catch (error) {
      if (version !== generation) return;
      failures++;
      notice(
        (error.name === "AbortError"
          ? "Le flux ne répond plus."
          : error.message) + " Reconnexion du suivi sans relancer la mission.",
      );
      q("#lk-connection").textContent =
        "Flux déconnecté · Dernières données conservées";
      connecte = false;
      signaler(
        "flux_interrompu",
        "Le flux d'évènements s'est interrompu. L'agent peut continuer à " +
          "travailler sans que cet écran le voie.",
      );
      q("#lk-reconnect").hidden = false;
      timer = setTimeout(
        () => follow(id, version),
        Math.min(10000, 1000 * failures),
      );
    } finally {
      clearTimeout(idle);
      clearTimeout(refreshTimer);
      if (streamController === controller) streamController = null;
    }
  }
  async function poll(id, version) {
    if (version !== generation) return;
    try {
      const state = await api("missions/" + encodeURIComponent(id));
      if (version !== generation) return;
      if (!connecte) signaler("suivi_retabli", "Le suivi a été rétabli.");
      failures = 0;
      connecte = true;
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
      connecte = false;
      signaler(
        "actualisation_impossible",
        "L'actualisation périodique a échoué : " + error.message,
      );
      q("#lk-reconnect").hidden = false;
      if (error.status === 401 || error.status === 404) return;
    }
    timer = setTimeout(
      () => poll(id, version),
      Math.min(10000, 1000 * Math.max(1, failures)),
    );
  }
  function libraryError(message) {
    q("#lk-library-error").textContent = message;
    q("#lk-library-error").hidden = !message;
  }
  function watchDate(value) {
    const d = new Date(value);
    return Number.isNaN(d.getTime())
      ? "Date inconnue"
      : d.toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" });
  }
  function action(label, callback, cls = "lk-add") {
    const button = el("button", cls, label);
    button.type = "button";
    button.onclick = callback;
    return button;
  }
  let pendingLibraryWatch = null;
  async function openLibrary(watchId = null) {
    pauseFollow();
    view = "library";
    q("#lk-home").hidden = true;
    q("#lk-work").hidden = true;
    q("#lk-library").hidden = false;
    q("#lk-nav").hidden = true;
    q("#lk-library").scrollIntoView({ block: "start" });
    libraryError("");
    pendingLibraryWatch = watchId;
    if (!token && !demo && !publicAccess) {
      libraryGeneration++;
      q("#lk-library-auth").hidden = false;
      q("#lk-watch-search").hidden = true;
      q("#lk-watch-list").replaceChildren();
      q("#lk-watch-detail").hidden = true;
      q("#lk-library-status").textContent =
        "Identifiez-vous pour retrouver les veilles conservées sur le serveur.";
      q("#lk-library-access").focus();
      return;
    }
    q("#lk-library-auth").hidden = true;
    return watchId ? loadWatch(watchId) : loadLibrary();
  }
  function libraryFailure(error) {
    libraryError(error.message);
    q("#lk-library-status").textContent =
      "Chargement interrompu. Vos données conservées ne sont pas modifiées.";
    if (error.status === 401) {
      token = "";
      q("#lk-library-auth").hidden = false;
      q("#lk-library-access").focus();
    }
  }
  async function loadLibrary(offset = 0) {
    const version = ++libraryGeneration;
    q("#lk-watch-detail").hidden = true;
    q("#lk-watch-list").hidden = false;
    q("#lk-watch-search").hidden = false;
    q("#lk-library-status").textContent = "Chargement de vos veilles…";
    libraryError("");
    try {
      const data = await api(
        "watches?query=" +
          encodeURIComponent(q("#lk-watch-query").value.trim()) +
          "&offset=" +
          offset,
      );
      if (version !== libraryGeneration || view !== "library") return;
      const host = q("#lk-watch-list");
      if (!offset) host.replaceChildren();
      q("#lk-watch-more")?.remove();
      q("#lk-library-status").textContent =
        `${data.total ?? data.watches.length} veille(s) · Consulter les résultats ne consomme aucun token.`;
      for (const watch of data.watches) {
        const card = el("article", "lk-watch-card");
        card.append(
          el(
            "span",
            "lk-watch-tag",
            names[watch.status] || watch.status || "Conservée",
          ),
          el("h3", "", watch.subject),
        );
        card.append(
          el(
            "p",
            "",
            `${watch.findings_count} constat(s) · ${watch.run_count} recherche(s) · Dernière activité : ${watchDate(watch.updated_at)}`,
          ),
        );
        const sources = el("div", "lk-watch-domains");
        for (const domain of watch.domains || [])
          sources.append(el("span", "", domain));
        card.append(sources);
        const buttons = el("div", "lk-watch-actions");
        buttons.append(
          action("Ouvrir la veille", () => loadWatch(watch.id)),
          action(
            "Dernier journal",
            () => openMission(watch.latest_mission_id),
            "lk-plain",
          ),
        );
        card.append(buttons);
        host.append(card);
      }
      if (offset + data.watches.length < data.total) {
        const more = action(
          "Afficher la suite",
          () => {
            more.disabled = true;
            loadLibrary(offset + data.watches.length).finally(() => {
              more.disabled = false;
            });
          },
          "lk-plain",
        );
        more.id = "lk-watch-more";
        host.append(more);
      }
      if (!offset && !data.watches.length)
        host.append(
          el(
            "p",
            "lk-empty",
            q("#lk-watch-query").value.trim()
              ? "Aucune veille pour cette recherche."
              : "Votre première veille apparaîtra ici. Lancez un sujet pour commencer.",
          ),
        );
    } catch (error) {
      if (version === libraryGeneration && view === "library")
        libraryFailure(error);
    }
  }
  async function loadWatch(id) {
    const version = ++libraryGeneration;
    q("#lk-library-status").textContent =
      "Chargement des résultats et des actualisations…";
    libraryError("");
    try {
      const watch = await api("watches/" + encodeURIComponent(id));
      if (version !== libraryGeneration || view !== "library") return;
      selectedWatch = watch;
      q("#lk-watch-search").hidden = true;
      q("#lk-watch-list").hidden = true;
      const host = q("#lk-watch-detail");
      host.hidden = false;
      host.replaceChildren();
      q("#lk-library-status").textContent =
        "Résultats cumulés · Chaque recherche conserve son propre journal.";
      host.append(
        action("← Toutes mes veilles", () => loadLibrary(), "lk-plain"),
      );
      const header = el("div", "lk-watch-detail-head");
      header.append(
        el("h2", "", watch.subject),
        el(
          "p",
          "",
          `Créée le ${watchDate(watch.created_at)} · Dernière activité : ${watchDate(watch.updated_at)}`,
        ),
      );
      const buttons = el("div", "lk-watch-actions");
      const refresh = action("Actualiser cette veille", () =>
        refreshWatch(watch, refresh),
      );
      buttons.append(
        refresh,
        action(
          "Modifier les sources et les limites",
          () => editWatch(watch),
          "lk-plain",
        ),
      );
      header.append(
        buttons,
        el(
          "p",
          "lk-accesshelp",
          "Actualiser recherche les nouveautés et peut consommer du crédit API. Les résultats déjà connus sont conservés.",
        ),
      );
      const sources = el("div", "lk-watch-domains");
      for (const domain of watch.domains || [])
        sources.append(el("span", "", domain));
      header.append(
        sources,
        el(
          "small",
          "lk-accesshelp",
          watch.auto_sources
            ? "Sources choisies automatiquement · sélection consultable dans le journal"
            : "Sources choisies manuellement",
        ),
      );
      host.append(header);
      host.append(briefOverview(watch.findings || []));
      host.append(el("h3", "lk-brief-heading", "02 · Les faits et leur portée"));
      for (const finding of watch.findings || []) {
        const article = el("article", "lk-result");
        const sourceLinks = el("div", "lk-source");
        for (const source of finding.source_links || [])
          sourceLinks.append(link(source.title || source.url, source.url));
        sourceLinks.append(el("span", "", findingDate(finding)));
        article.append(
          sourceLinks,
          el("h3", "", finding.title),
          ...briefFinding(finding),
          el("div", "lk-caveat", confidenceLabel(finding)),
        );
        for (const caveat of finding.caveats || [])
          article.append(el("div", "lk-caveat", caveat));
        if (finding.change === "updated")
          article.append(el("span", "lk-watch-tag", "Information actualisée"));
        const details = el("details", "lk-caveat");
        details.append(el("summary", "", "Preuves et provenance"));
        for (const evidence of finding.evidence || [])
          details.append(el("blockquote", "", evidence.quote));
        if (finding.mission_id)
          details.append(
            action(
              "Ouvrir la recherche d’origine",
              () => openMission(finding.mission_id),
              "lk-plain",
            ),
          );
        article.append(details);
        host.append(article);
      }
      if (!watch.findings?.length)
        host.append(
          el(
            "p",
            "lk-empty",
            "Aucun constat enregistré pour le moment. Les recherches et leurs éventuelles erreurs sont consultables ci-dessous.",
          ),
        );
      host.append(briefLimits(watch.findings || [], (watch.runs || []).some(run => run.status !== "completed")));
      const runs = el("section", "lk-watch-runs");
      runs.append(el("h3", "", "Historique des recherches"));
      for (const run of [...(watch.runs || [])].sort(
        (a, b) => new Date(b.created_at) - new Date(a.created_at),
      )) {
        const row = el("div", "lk-watch-run");
        const detail = el("div");
        detail.append(
          el(
            "strong",
            "",
            `${watchDate(run.created_at)} · ${names[run.status] || run.status}`,
          ),
        );
        detail.append(
          el(
            "small",
            "",
            `${run.actions_used ?? 0} action(s) · ${run.new_findings_count ?? 0} nouveauté(s) · ${run.updated_findings_count ?? 0} constat(s) actualisé(s)`,
          ),
        );
        row.append(
          detail,
          action("Résultats et journal", () => openMission(run.id), "lk-plain"),
        );
        runs.append(row);
      }
      host.append(runs);
    } catch (error) {
      if (version === libraryGeneration && view === "library")
        libraryFailure(error);
    }
  }
  function missionRequest(state, overrides = {}) {
    return {
      subject: state.subject,
      domains: state.auto_sources ? [] : state.domains,
      auto_sources: Boolean(state.auto_sources),
      action_budget: state.action_budget,
      duration_minutes: Math.round(state.duration_seconds / 60),
      ...overrides,
    };
  }
  async function refreshWatch(watch, button) {
    if (launching) return;
    button.disabled = true;
    libraryError("");
    try {
      const previous = await api(
        "missions/" + encodeURIComponent(watch.latest_mission_id),
      );
      await launchRequest(
        missionRequest(previous, {
          subject: watch.subject,
          watch_id: watch.id,
          force_refresh: true,
        }),
      );
    } catch (error) {
      libraryFailure(error);
    } finally {
      button.disabled = false;
    }
  }
  async function editWatch(watch) {
    libraryError("");
    try {
      const previous = await api(
        "missions/" + encodeURIComponent(watch.latest_mission_id),
      );
      newWatch();
      selectedWatch = watch;
      q("#lk-topic").value = watch.subject;
      q("#lk-budget").value = previous.action_budget;
      q("#lk-duration").value = Math.round(previous.duration_seconds / 60);
      domains = [...watch.domains];
      q("#lk-source-mode").value = watch.domains.length ? "manual" : "auto";
      drawDomains();
      updateSourceMode();
      updateLimits();
      q(".lk-submit").textContent = "Actualiser cette veille";
    } catch (error) {
      libraryFailure(error);
    }
  }
  async function openMission(id) {
    libraryError("");
    try {
      const state = await api("missions/" + encodeURIComponent(id));
      activateMission(state);
    } catch (error) {
      libraryFailure(error);
    }
  }
  function activateMission(state) {
    pauseFollow();
    libraryGeneration++;
    failures = 0;
    notice("");
    showTab("results");
    render(state);
    q("#lk-work").scrollIntoView({ block: "start" });
    if (state.reuse)
      notice(
        state.reuse.reason === "recent_completed"
          ? "Cette veille a déjà été réalisée au cours des dernières 24 heures. Résultats existants réutilisés : aucun nouvel appel au modèle."
          : "Cette veille est déjà en cours. Vous retrouvez la même mission, sans nouveau lancement.",
      );
    q("#lk-connection").textContent = terminal.has(state.status)
      ? "Recherche conservée · Aucun appel au modèle pour cette consultation"
      : "Connexion au suivi…";
    if (!terminal.has(state.status)) follow(state.id, generation);
  }
  function showSimilar(candidates, request) {
    pendingRequest = request;
    view = "home";
    q("#lk-home").hidden = false;
    q("#lk-work").hidden = true;
    q("#lk-library").hidden = true;
    const host = q("#lk-similar");
    host.hidden = false;
    host.replaceChildren(
      el("strong", "", "Une veille proche existe déjà"),
      el(
        "p",
        "",
        "Choisissez de l’enrichir ou de conserver un sujet distinct. Aucune recherche n’a encore été lancée.",
      ),
    );
    for (const watch of candidates)
      host.append(
        action(`Enrichir « ${watch.subject} »`, () =>
          launchRequest({
            ...pendingRequest,
            watch_id: watch.id,
            force_refresh: true,
          }),
        ),
      );
    host.append(
      action(
        "Créer une veille distincte",
        () => launchRequest({ ...pendingRequest, allow_new: true }),
        "lk-plain",
      ),
    );
    host.scrollIntoView({ block: "center", behavior: "smooth" });
  }
  async function launchRequest(request) {
    if (launching) return;
    launching = true;
    q(".lk-submit").disabled = true;
    root
      .querySelectorAll("#lk-similar button")
      .forEach((b) => (b.disabled = true));
    formError("");
    try {
      const config = await api("config");
      renderApiControl(config);
      if (!config.provider_ready)
        throw new Error(
          "La clé Anthropic n’est pas configurée sur le serveur.",
        );
      const state = await api("missions", {
        method: "POST",
        body: JSON.stringify(request),
      });
      q("#lk-similar").hidden = true;
      q("#lk-access").value = "";
      resumePending = false;
      activateMission(state);
    } catch (error) {
      if (error.status === 409 && error.detail?.code === "similar_watches")
        showSimilar(error.detail.candidates || [], request);
      else if (view === "library") libraryFailure(error);
      else formError(error.message);
    } finally {
      launching = false;
      q(".lk-submit").disabled = false;
      root
        .querySelectorAll("#lk-similar button")
        .forEach((b) => (b.disabled = false));
    }
  }
  function briefOverview(findings) {
    const section = el("section", "lk-brief-overview");
    section.append(el("h3", "lk-brief-heading", "01 · À retenir"));
    if (!findings.length) {
      section.append(el("p", "lk-caveat", "Les points clés apparaîtront dès qu’un constat sera sauvegardé avec sa preuve."));
      return section;
    }
    const list = el("ol", "lk-brief-list");
    for (const finding of findings.slice(0, 3)) list.append(el("li", "", finding.title));
    section.append(list, el("p", "lk-caveat", `${findings.length} constat(s) documenté(s) · Les dates et les preuves sont précisées ci-dessous.`));
    return section;
  }
  function briefFinding(finding) {
    const impact = el("div", "lk-interest");
    impact.append(el("strong", "lk-brief-label", "Ce que cela implique"), el("p", "", finding.developer_impact));
    return [el("strong", "lk-brief-label", "Ce que dit la source"), el("p", "", finding.summary), impact];
  }
  function briefLimits(findings, partial) {
    const section = el("section", "lk-brief-limits");
    section.append(el("h3", "lk-brief-heading", "03 · Limites et points à vérifier"));
    const list = el("ul", "lk-brief-list");
    if (partial) list.append(el("li", "", "Recherche partielle : la couverture du sujet n’est pas exhaustive. Consultez le statut et le journal."));
    const undated = findings.filter(f => f.date_status === "unknown" || !f.event_date).length;
    const old = findings.filter(f => f.date_status === "outside_window").length;
    if (undated) list.append(el("li", "", `${undated} constat(s) sans date confirmée : leur récence n’est pas établie.`));
    if (old) list.append(el("li", "", `${old} constat(s) hors période : à lire comme contexte, pas comme nouveautés récentes.`));
    if (findings.some(f => f.confidence === "single_source")) list.append(el("li", "", "Certains constats reposent sur une seule source : vérifiez-les avant une décision importante."));
    list.append(el("li", "", "Les implications sont une interprétation. Les extraits cités et leurs liens permettent de vérifier les faits."));
    section.append(list);
    return section;
  }
  function updateSourceMode() {
    const automatic = q("#lk-source-mode").value === "auto";
    q("#lk-manual-sources").hidden = automatic;
    q("#lk-source-help").textContent = automatic
      ? "Lockin sélectionne jusqu’à 5 sites pertinents, en privilégiant les publications d’origine. Vous retrouverez les sources avec les résultats."
      : "L’agent consultera uniquement ces domaines. Ajoutez au moins une source autorisée.";
    updateLimits();
  }
  let apiEnabled = null;
  let changingApi = false;
  function renderApiControl(config) {
    if (demo) return;
    if (typeof config.public_access === "boolean") {
      publicAccess = config.public_access;
      q("#lk-auth").hidden = publicAccess;
      q("#lk-access").required = !publicAccess;
      if (publicAccess) q("#lk-library-auth").hidden = true;
    }
    apiEnabled = config.api_enabled;
    const button = q("#lk-api-toggle");
    button.disabled = changingApi || typeof apiEnabled !== "boolean";
    button.textContent = apiEnabled ? "Mettre les recherches en pause" : "Réactiver les recherches";
    button.setAttribute("aria-label", button.textContent + (apiEnabled ? " — actuellement activée" : " — actuellement désactivée"));
    const status = q("#lk-api-status");
    status.hidden = false;
    status.textContent = apiEnabled
      ? "Les recherches sont disponibles. Leur coût estimé s’affiche pendant la veille."
      : "Les recherches sont en pause pour tout le monde. Vos veilles restent accessibles. Les recherches déjà envoyées peuvent avoir été facturées.";
  }
  async function refreshApiControl() {
    if (demo || changingApi) return;
    try { renderApiControl(await api("config")); }
    catch {
      apiEnabled = null;
      q("#lk-api-toggle").disabled = true;
      q("#lk-api-toggle").textContent = "Connexion à vérifier";
      q("#lk-api-status").hidden = false;
      q("#lk-api-status").textContent = "Impossible de vérifier si les recherches sont disponibles. Vérifiez votre connexion.";
    }
  }
  q("#lk-api-toggle").onclick = async () => {
    if (changingApi || typeof apiEnabled !== "boolean") return;
    changingApi = true;
    q("#lk-api-toggle").disabled = true;
    try {
      const result = await api("control", { method: "POST", body: JSON.stringify({ enabled: !apiEnabled }) });
      renderApiControl(result);
      if (result.stopping_missions?.length)
        q("#lk-api-status").textContent += " Arrêt de la mission en cours demandé ; sa confirmation apparaît dans le journal.";
    } catch {
      q("#lk-api-status").hidden = false;
      q("#lk-api-status").textContent = "Changement non confirmé. Vérification de l’état du serveur…";
    } finally {
      changingApi = false;
      await refreshApiControl();
    }
  };
  for (const selector of ["#lk-access", "#lk-library-access"])
    q(selector).addEventListener("change", () => {
      token = q(selector).value.trim();
      refreshApiControl();
    });
  setInterval(refreshApiControl, 15000);
  q("#lk-source-mode").onchange = updateSourceMode;
  q("#lk-library-nav").onclick = () => openLibrary();
  q("#lk-library-new").onclick = newWatch;
  q("#lk-mission-watch").onclick = () => openLibrary(mission.watch_id);
  q("#lk-watch-search").onsubmit = (event) => {
    event.preventDefault();
    loadLibrary();
  };
  q("#lk-library-reload").onclick = () => openLibrary();
  q("#lk-library-auth").onsubmit = (event) => {
    event.preventDefault();
    token = q("#lk-library-access").value.trim();
    q("#lk-library-access").value = "";
    openLibrary(pendingLibraryWatch);
  };
  q("#lk-form").onsubmit = (e) => e.preventDefault();
  q(".lk-submit").onclick = async () => {
    if (launching || !q("#lk-form").reportValidity()) return;
    token = q("#lk-access").value.trim() || token;
    if (resumePending && remembered()) {
      try {
        const state = await api("missions/" + encodeURIComponent(remembered()));
        q("#lk-access").value = "";
        resumePending = false;
        activateMission(state);
      } catch (error) {
        formError(error.message);
        if (error.status === 404) {
          remember(null);
          resumePending = false;
          q(".lk-submit").textContent = "Lancer la veille";
        }
      }
      return;
    }
    const automatic = q("#lk-source-mode").value === "auto";
    if (!automatic && !domains.length) {
      formError("Ajoutez au moins un domaine autorisé.");
      return;
    }
    await launchRequest({
      subject: q("#lk-topic").value.trim(),
      domains: automatic ? [] : domains,
      auto_sources: automatic,
      action_budget: Number(q("#lk-budget").value),
      duration_minutes: Number(q("#lk-duration").value),
      ...(selectedWatch
        ? { watch_id: selectedWatch.id, force_refresh: true }
        : {}),
    });
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
      closeStream();
      render(state);
      if (!terminal.has(state.status)) follow(state.id, generation);
    } catch (error) {
      notice(error.message + " L’arrêt n’est pas confirmé.");
      q("#lk-stop").disabled = false;
    }
  };
  q("#lk-nav").onclick = newWatch;
  root
    .querySelectorAll("[data-tab]")
    .forEach((button) => (button.onclick = () => showTab(button.dataset.tab)));
  q("#lk-reconnect").onclick = () => {
    clearTimeout(timer);
    generation++;
    closeStream();
    view = "home";
    resumePending = true;
    q("#lk-home").hidden = false;
    q("#lk-library").hidden = true;
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
          window.LockinJournal.buildExport(mission, incidents, {
            simulated: demo,
          }),
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
    resumePending = true;
    q(".lk-submit").textContent = "Retrouver ma veille";
    q("#lk-accesshelp").textContent =
      "Saisissez votre code pour retrouver la dernière mission de cet onglet.";
  }
  if (demo) {
    q("#lk-api-toggle").hidden = true;
    q("#lk-demo-banner").hidden = false;
    q("#lk-auth").hidden = true;
    q("#lk-access").required = false;
    q("#lk-demo-options").hidden = false;
    q(".lk-proto").textContent = "DÉMONSTRATION";
    q("#lk-connection").textContent = "Simulation locale · Aucun appel API";
  }
  drawDomains();
  updateSourceMode();
  updateLimits();
  if (!demo) refreshApiControl();
  if (window.lucide)
    window.lucide.createIcons({ attrs: { width: 16, height: 16 } });
})();
