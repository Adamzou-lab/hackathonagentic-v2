/* Journal de supervision : horodatage, diagnostic des pannes, incidents client.
 *
 * Ce module ne contient que des fonctions pures, sans DOM ni réseau, afin
 * d'être vérifiable en dehors du navigateur et sans appel API.
 *
 * Règle qui gouverne tout le fichier : le serveur horodate ce qu'il a fait,
 * le navigateur horodate ce qu'il a constaté. Les deux ne se mélangent jamais,
 * et l'heure d'une détection n'est jamais présentée comme l'heure d'une panne.
 */
(function (root) {
  "use strict";

  const pad = (n, w = 2) => String(n).padStart(w, "0");

  /* Décalage du fuseau du navigateur, au format UTC+HH:MM. */
  function zone(d) {
    const offset = -d.getTimezoneOffset();
    const sign = offset < 0 ? "-" : "+";
    const abs = Math.abs(offset);
    return "UTC" + sign + pad(Math.floor(abs / 60)) + ":" + pad(abs % 60);
  }

  /* Horodatage absolu à la milliseconde, avec le fuseau, plus l'ISO d'origine. */
  function stamp(at) {
    const d = new Date(at);
    if (Number.isNaN(d.getTime()))
      return { valid: false, absolute: "Horodatage illisible", iso: String(at ?? ""), zone: "" };
    const jour = pad(d.getDate()) + "/" + pad(d.getMonth() + 1) + "/" + d.getFullYear();
    const heure =
      pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds()) +
      "." + pad(d.getMilliseconds(), 3);
    return { valid: true, absolute: jour + " " + heure + " " + zone(d), iso: d.toISOString(), zone: zone(d) };
  }

  /* Temps écoulé depuis le début de la mission, conservé tel qu'affiché avant. */
  function elapsed(at, createdAt) {
    const a = new Date(at), b = new Date(createdAt);
    if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return null;
    return (a - b) / 1000;
  }

  /* Dépendance concernée, cause, réaction de l'agent, pour chaque code connu. */
  const PANNES = {
    timeout:                     ["Fournisseur ou site distant", "Aucune réponse dans le délai imparti", "Appel abandonné, la boucle continue"],
    attempts_exhausted:          ["Site distant", "Deux tentatives ont échoué sur cette source", "Source abandonnée pour toute la mission"],
    document_redirect_rejected:  ["Site distant", "La page redirige ailleurs avant d'être lue", "Redirection refusée, page non lue"],
    blocked_url:                 ["Contrôle de périmètre", "Adresse hors des domaines autorisés", "Requête refusée avant tout accès réseau"],
    invalid_evidence:            ["Modèle", "L'extrait cité ne figure pas dans la page enregistrée", "Constat rejeté, rien n'est écrit au rapport"],
    invalid_input:               ["Modèle", "Arguments non conformes à la signature de l'outil", "Appel refusé avant exécution"],
    unknown_tool:                ["Modèle", "Outil inexistant demandé", "Appel refusé"],
    tool_disabled:               ["Contrôle de périmètre", "Outil désactivé pour cette mission", "Appel refusé"],
    model_missing_action:        ["Modèle", "Aucune action proposée dans la réponse", "Tour perdu, la boucle repart"],
    rate_limited:                ["Fournisseur", "Quota de requêtes dépassé", "Appel abandonné, la boucle continue"],
    too_large:                   ["Site distant", "Réponse trop volumineuse", "Lecture interrompue"],
    unsupported_content:         ["Site distant", "Format de contenu non traité", "Page ignorée"],
    unavailable:                 ["Fournisseur ou site distant", "Service indisponible", "Appel abandonné"],
    storage_failure:             ["Stockage local", "Écriture impossible dans le journal", "Mission arrêtée : sans journal, plus de preuve"],
    idempotency_conflict:        ["Stockage local", "Même clé réutilisée avec un contenu différent", "Écriture refusée"],
    cancelled:                   ["Opérateur", "Arrêt demandé pendant l'appel", "Appel interrompu proprement"],
    execution_error:             ["Programme", "Erreur inattendue pendant l'exécution", "Mission arrêtée"],
    budget_exhausted:            ["Contrôle de périmètre", "Budget d'actions épuisé", "Mission close, résultats conservés"],
    deadline_reached:            ["Contrôle de périmètre", "Durée maximale atteinte", "Mission close, résultats conservés"],
    anthropic_stream_error:      ["Fournisseur", "Flux interrompu par le fournisseur", "Appel abandonné"],
  };

  function diagnose(code) {
    if (!code) return null;
    const known = PANNES[code];
    if (known) return { code, dependency: known[0], cause: known[1], reaction: known[2], known: true };
    const http = /^anthropic_http_(\d{3})$/.exec(code);
    if (http)
      return { code, dependency: "Fournisseur", cause: "Réponse HTTP " + http[1] + " du fournisseur",
               reaction: "Mission arrêtée", known: true };
    const search = /^web_search_(.+)$/.exec(code);
    if (search)
      return { code, dependency: "Recherche web", cause: "Le service de recherche a renvoyé « " + search[1] + " »",
               reaction: "Recherche abandonnée pour ce tour", known: true };
    return { code, dependency: "Dépendance non identifiée", cause: "Code non répertorié : " + code,
             reaction: "Voir le détail brut de l'évènement", known: false };
  }

  /* Code d'échec porté par un évènement, quel que soit l'endroit où il figure. */
  function failureCode(event) {
    const d = (event && event.data) || {};
    return d.code || (d.result && d.result.error) || d.error || null;
  }

  /* Quatre situations distinctes, à ne jamais confondre.
   *
   * `connected` décrit le navigateur, `status` décrit l'agent. Une connexion
   * perdue ne dit rien de l'agent : il peut très bien continuer à travailler.
   */
  function situation(status, connected) {
    if (!connected)
      return { key: "connection_lost", source: "navigateur",
               label: "Connexion au suivi perdue",
               detail: "L'agent n'est pas arrêté pour autant : cet écran ne reçoit plus ses évènements, c'est tout. Son état réel reste à confirmer.",
               severity: "warn" };
    if (status === "stopping")
      return { key: "stop_requested", source: "serveur",
               label: "Arrêt demandé",
               detail: "Le serveur a reçu la demande. Aucune nouvelle action ne sera lancée ; un appel déjà parti se termine.",
               severity: "warn" };
    if (status === "stopped")
      return { key: "stop_confirmed", source: "serveur",
               label: "Arrêt confirmé",
               detail: "L'agent s'est arrêté. L'état affiché est définitif.",
               severity: "ok" };
    if (status === "failed")
      return { key: "failed", source: "serveur",
               label: "Échec de la mission",
               detail: "La mission s'est terminée sur une erreur. La cause figure au journal.",
               severity: "error" };
    return { key: "running", source: "serveur",
             label: "Suivi actif", detail: "", severity: "ok" };
  }

  /* Incident constaté par le navigateur. Jamais un évènement du journal serveur. */
  function incident(kind, detail, now) {
    const d = now ? new Date(now) : new Date();
    return {
      origin: "navigateur",
      kind,
      detail: detail || "",
      detected_at: d.toISOString(),
      // Formulation volontairement prudente : le navigateur date sa détection,
      // pas l'évènement qui l'a causée. L'écart entre les deux est inconnu.
      note: "Heure de détection par le navigateur. L'heure réelle de la coupure côté serveur est inconnue.",
    };
  }

  /* Export : journal serveur et incidents client restent séparés. */
  function buildExport(mission, incidents, options) {
    const opts = options || {};
    return {
      mission_id: mission ? mission.id : null,
      subject: mission ? mission.subject : null,
      simulated: !!opts.simulated,
      exported_at: (opts.now ? new Date(opts.now) : new Date()).toISOString(),
      lecture:
        "events provient du serveur et fait foi (seq, at, kind, data). " +
        "client_incidents est constaté par le navigateur : ces horodatages sont des heures de détection, " +
        "jamais l'heure certaine d'une coupure côté serveur.",
      events: (mission && mission.events) || [],
      client_incidents: incidents || [],
    };
  }

  const api = { stamp, elapsed, zone, diagnose, failureCode, situation, incident, buildExport, PANNES };
  if (typeof module === "object" && module.exports) module.exports = api;
  root.LockinJournal = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
