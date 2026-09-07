"use strict";

/**
 * Interface Lockin. Contrat serveur : voir API.md (backend FastAPI d'Adam).
 *
 *   POST /api/missions            { subject, domains[], action_budget, duration_minutes } → 202, instantané
 *   GET  /api/missions/:id        instantané
 *   POST /api/missions/:id/stop   arrêt idempotent, instantané
 *
 * Toutes les routes /api/ exigent `Authorization: Bearer <LOCKIN_ACCESS_TOKEN>`.
 * Le jeton opérateur est saisi dans le formulaire et gardé en mémoire de la
 * page uniquement — jamais dans l'URL, ni dans le stockage du navigateur.
 *
 * L'instantané serveur (anglais) est converti par `adapterMission` vers la
 * forme interne (français) utilisée par tout le rendu. Le simulateur du mode
 * démo produit directement cette forme interne.
 */

const MODE_DEMO = new URLSearchParams(location.search).has("demo");
const INTERVALLE_RAFRAICHISSEMENT_MS = 1000;
const MAX_DOMAINES = 5;
const MAX_SUJET = 500;
const MAX_BUDGET = 100;
const MAX_DUREE = 30;
const LONGUEUR_MIN_JETON = 32;
const MOTIF_DOMAINE = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i;

let jetonMemoire = "";

const LIBELLES_ETAT = {
  pending: "En attente",
  running: "En cours",
  stopping: "Arrêt en cours",
  stopped: "Arrêté (manuel)",
  completed: "Terminé",
  budget_exhausted: "Arrêté (budget épuisé)",
  deadline_reached: "Arrêté (échéance)",
  failed: "Erreur",
};

const DESCRIPTIONS_ETAT = {
  pending: "Mission créée, l'agent démarre.",
  running: "L'agent travaille seul. Vous pouvez fermer cette page, il continue.",
  stopping: "Arrêt reçu par le serveur : plus aucune nouvelle action, l'appel en cours se termine.",
  stopped: "Arrêt manuel. L'état ci-dessous est figé et reste consultable.",
  completed: "L'agent a terminé de lui-même, sans épuiser le budget ni la durée.",
  budget_exhausted: "Budget d'actions épuisé. Tout ce qui a été trouvé est conservé.",
  deadline_reached: "Durée maximale atteinte. Tout ce qui a été trouvé est conservé.",
  failed: "Panne bloquante. Ce qui a été journalisé reste consultable.",
};

const ETATS_TERMINAUX = new Set(["stopped", "completed", "budget_exhausted", "deadline_reached", "failed"]);
const ETATS_ACTIFS = new Set(["pending", "running", "stopping"]);

const LIBELLES_ACTION = {
  search_web: "recherche web",
  read_page: "lecture d'une page",
  save_finding: "sauvegarde d'un constat",
};

const TYPE_PAR_OUTIL = { search_web: "recherche", read_page: "lecture", save_finding: "constat" };

const LIBELLES_CONFIANCE = {
  single_source: ["Source unique", "neutre"],
  corroborated: ["Corroboré", "succes"],
  conflicting: ["Contradictoire", "danger"],
};

const LIBELLES_STATUT_DATE = {
  in_window: "dans la fenêtre",
  outside_window: "hors fenêtre",
  unknown: "date inconnue",
};

const LIBELLES_ERREUR = {
  invalid_input: "paramètres invalides",
  blocked_url: "URL refusée (hors domaines autorisés ou adresse privée)",
  timeout: "délai dépassé",
  unavailable: "page injoignable",
  rate_limited: "débit limité par le site",
  too_large: "page trop volumineuse",
  unsupported_content: "contenu non pris en charge",
  invalid_evidence: "citation introuvable dans la page",
  idempotency_conflict: "conflit d'idempotence",
  storage_failure: "échec d'écriture du journal",
  cancelled: "annulé",
  budget_exhausted: "budget épuisé",
  attempts_exhausted: "deux tentatives déjà faites sur cette URL",
  unknown_tool: "outil inconnu",
  invalid_finish: "fin de mission invalide",
  web_search_unavailable: "recherche web indisponible sur le compte",
  execution_error: "erreur d'exécution",
};

function libelleErreur(code) {
  if (!code) return "";
  if (String(code).startsWith("anthropic_http_")) return `erreur fournisseur (HTTP ${String(code).slice(15)})`;
  return LIBELLES_ERREUR[code] || String(code);
}

const MESSAGES_HTTP = {
  401: "Jeton opérateur incorrect.",
  403: "Accès refusé.",
  404: "Mission introuvable.",
  409: "Une mission est déjà en cours sur ce serveur : une seule à la fois.",
  503: "Configuration serveur incomplète : clé Anthropic ou jeton opérateur manquant.",
};

// ---------- API réelle ----------

function messageErreurHttp(statut, donnees) {
  if (MESSAGES_HTTP[statut]) return MESSAGES_HTTP[statut];
  const detail = donnees && donnees.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((d) => String(d.msg || "").replace(/^Value error, /, "")).filter(Boolean);
    if (messages.length) return messages.join(" ");
  }
  return `Le serveur a répondu ${statut}.`;
}

async function requete(chemin, methode = "GET", corps) {
  const entetes = { Authorization: `Bearer ${jetonMemoire}` };
  if (corps !== undefined) entetes["Content-Type"] = "application/json";
  const reponse = await fetch(chemin, {
    method: methode,
    headers: entetes,
    body: corps === undefined ? undefined : JSON.stringify(corps),
  });
  const donnees = await reponse.json().catch(() => ({}));
  if (!reponse.ok) throw new Error(messageErreurHttp(reponse.status, donnees));
  return adapterMission(donnees);
}

function heureDe(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? String(iso || "") : date.toTimeString().slice(0, 8);
}

// Traduit un événement du journal serveur (kind + data) en une ligne lisible.
function decrireEvenement(evenement, budgetMax) {
  const kind = evenement.kind;
  const data = evenement.data || {};
  const outil = LIBELLES_ACTION[data.tool] || data.tool || "";
  let type = "interne";
  let message = "";
  let budgetRestant = null;
  const resteApres = (actionsUtilisees) =>
    typeof actionsUtilisees === "number" && budgetMax ? Math.max(0, budgetMax - actionsUtilisees) : null;

  switch (kind) {
    case "created": {
      const r = data.request || {};
      type = "etat";
      message = `Mission créée : « ${r.subject ?? ""} », ${(r.domains || []).length} domaine(s), budget ${r.action_budget ?? "?"}, durée ${r.duration_minutes ?? "?"} min`;
      break;
    }
    case "started":
      type = "etat";
      message = "Démarrage de l'agent";
      break;
    case "stop_requested":
      type = "etat";
      message = "Arrêt demandé par l'opérateur : plus aucune nouvelle action";
      break;
    case "finished":
      type = "etat";
      message = `Fin de mission : ${LIBELLES_ETAT[data.status] || data.status}${data.error ? ` — ${libelleErreur(data.error)}` : ""}`;
      budgetRestant = resteApres(data.actions_used);
      break;
    case "action_reserved":
      message = `Action ${data.actions_used}/${budgetMax ?? "?"} réservée sur le budget`;
      budgetRestant = resteApres(data.actions_used);
      break;
    case "action_started": {
      type = TYPE_PAR_OUTIL[data.tool] || "interne";
      const p = data.parameters || {};
      let detail = "";
      if (data.tool === "search_web") detail = `« ${p.query ?? ""} » (k=${p.k ?? "?"})`;
      else if (data.tool === "read_page") detail = p.url ?? "";
      else if (data.tool === "save_finding") detail = `« ${(p.finding && p.finding.title) ?? ""} »`;
      else if (p.validation) detail = `(${libelleErreur(p.validation)})`;
      message = `Action n°${data.action_number ?? "?"} : ${outil} ${detail}`.trim();
      break;
    }
    case "action_finished": {
      type = TYPE_PAR_OUTIL[data.tool] || "interne";
      const r = data.result || {};
      if (r.error) message = `${outil} terminée en échec : ${libelleErreur(r.error)}`;
      else if (data.tool === "read_page") message = `Page lue : ${r.title || r.final_url || r.requested_url || ""}`;
      else if (data.tool === "search_web") {
        const n = Array.isArray(r) ? r.length : Array.isArray(r.results) ? r.results.length : null;
        message = n === null ? "Recherche terminée" : `Recherche terminée : ${n} résultat(s)`;
      } else if (data.tool === "save_finding") message = `Constat ${r.disposition === "already_saved" ? "déjà connu" : "enregistré"}`;
      else message = `${outil} terminée`;
      break;
    }
    case "page_attempt":
      type = "lecture";
      message = `Tentative ${data.attempt}/2 : ${data.url}`;
      break;
    case "page_saved":
      type = "lecture";
      message = `Page conservée : ${data.url}`;
      break;
    case "finding_saved":
      type = "constat";
      message = `Constat ${data.disposition === "already_saved" ? "déjà connu (déduplication)" : "nouveau"}${data.finding_id ? ` #${String(data.finding_id).slice(0, 8)}` : ""}`;
      break;
    case "tool_error":
      type = "erreur";
      message = `Erreur ${outil || ""} : ${libelleErreur(data.code)}`.replace("  ", " ");
      break;
    case "model_started":
      message = `Appel au modèle n°${data.model_calls_used}`;
      break;
    case "model_finished": {
      const u = data.usage || {};
      const jetons = u.input_tokens != null ? ` (${u.input_tokens} → ${u.output_tokens ?? "?"} jetons)` : "";
      const proposition = data.proposed_action ? ` : propose ${LIBELLES_ACTION[data.proposed_action] || data.proposed_action}` : "";
      message = `Réponse du modèle${proposition}${jetons}`;
      break;
    }
    case "network_started":
      message = `Requête réseau n°${data.network_requests_used}`;
      break;
    default:
      message = `${kind}${Object.keys(data).length ? ` ${JSON.stringify(data)}` : ""}`;
  }

  return { seq: evenement.seq, ts: heureDe(evenement.at), type, message, budget_restant: budgetRestant };
}

function adapterMission(m) {
  const urlParSource = new Map((m.sources || []).filter((s) => s.source_id).map((s) => [s.source_id, s.url]));
  return {
    id: m.id,
    statut: m.status,
    sujet: m.subject,
    domaines: m.domains || [],
    budget: { restant: m.actions_remaining ?? 0, max: m.action_budget ?? 0 },
    temps: { ecoule_s: m.elapsed_seconds ?? 0, max_s: m.duration_seconds ?? 0 },
    action_en_cours: m.current_action || null,
    appels_modele: m.model_calls_used ?? 0,
    requetes_reseau: m.network_requests_used ?? 0,
    sources: (m.sources || []).map((s) => ({
      url: s.url,
      titre: s.title || "",
      statut: s.status === "ok" ? "ok" : "echec",
      erreur: s.error || null,
    })),
    constats: (m.findings || []).map((f) => ({
      id: f.finding_id,
      titre: f.title,
      resume: f.summary,
      interet_developpeur: f.developer_impact,
      preuves: (f.evidence || []).map((e) => ({
        url: urlParSource.get(e.source_id) || null,
        source_id: e.source_id,
        extrait: e.quote || "",
      })),
      date_evenement: f.event_date || null,
      statut_date: f.date_status,
      confiance: f.confidence,
      reserves: f.caveats || [],
    })),
    journal: (m.events || []).map((e) => decrireEvenement(e, m.action_budget)),
    synthese: (m.summary && m.summary.text) || "",
    partielle: m.summary ? Boolean(m.summary.partial) : null,
    erreur: m.error ? { message: libelleErreur(m.error) } : null,
  };
}

const apiReel = {
  creerMission(valeurs) {
    return requete("/api/missions", "POST", {
      subject: valeurs.sujet,
      domains: valeurs.domaines,
      action_budget: valeurs.budget,
      duration_minutes: valeurs.duree,
    });
  },
  obtenirMission(id) {
    return requete(`/api/missions/${encodeURIComponent(id)}`);
  },
  arreterMission(id) {
    return requete(`/api/missions/${encodeURIComponent(id)}/stop`, "POST");
  },
};

// ---------- Simulateur (mode démo, `?demo` dans l'URL) ----------
// Données simulées dans le navigateur, sans aucun appel réseau. Sert à
// regarder l'interface sans backend. Jamais actif par défaut, et un bandeau
// l'annonce à l'écran : ce n'est pas une démonstration.

function creerSimulateur() {
  const CHEMINS = ["/blog/nouveautes-agents", "/docs/changelog", "/releases", "/annonces/septembre", "/guide/outils", "/notes-de-version"];
  const TITRES = [
    "Nouvelle version d'un SDK d'agents (simulé)",
    "Prise en charge des outils typés (simulé)",
    "Limites de débit revues (simulé)",
    "Journal d'exécution exportable (simulé)",
  ];
  const RESUMES = [
    "Une mise à jour annonce un mode d'exécution longue avec budget explicite.",
    "La documentation décrit un schéma d'outil avec signature typée et effet de bord déclaré.",
    "Un billet précise de nouvelles limites par domaine et un délai par appel.",
    "Une note de version ajoute l'export du journal au format JSON.",
  ];
  const IMPACTS = [
    "Permet de borner une mission sans surveiller chaque étape.",
    "Réduit les appels d'outils invalides côté modèle.",
    "À prendre en compte pour calibrer le budget.",
    "Facilite la reconstruction d'état après un arrêt.",
  ];
  const EXTRAITS = [
    "les missions longues acceptent désormais un budget d'actions explicite",
    "chaque outil déclare une signature typée et son effet de bord",
    "une limite par domaine et un délai de quinze secondes par appel",
    "le journal complet peut être exporté au format JSON",
  ];

  let mission = null;
  let phase = "recherche";
  let source = null;
  let compteur = 0;
  let okDepuisConstat = 0;
  let ticksArret = 0;
  const urlsEnEchec = new Set();
  const tentatives = new Map();

  const heure = () => new Date().toTimeString().slice(0, 8);
  const attendre = () => new Promise((resoudre) => setTimeout(resoudre, 120));

  function copie() {
    const c = JSON.parse(JSON.stringify(mission));
    c.partielle = mission.statut !== "completed" || mission.sources.some((s) => s.statut === "echec");
    c.synthese = mission.constats.length ? "" : "Aucun résultat exploitable pour le moment.";
    return c;
  }

  function journaliser(type, message) {
    mission.journal.push({ seq: mission.journal.length + 1, ts: heure(), type, message, budget_restant: mission.budget.restant });
  }

  function consommer() {
    mission.budget.restant = Math.max(0, mission.budget.restant - 1);
  }

  function terminerSiLimiteAtteinte() {
    if (mission.budget.restant <= 0) {
      mission.statut = "budget_exhausted";
      mission.action_en_cours = null;
      journaliser("etat", "Fin de mission : budget épuisé");
      return true;
    }
    if (mission.temps.ecoule_s >= mission.temps.max_s) {
      mission.statut = "deadline_reached";
      mission.action_en_cours = null;
      journaliser("etat", `Fin de mission : échéance de ${mission.temps.max_s / 60} min atteinte`);
      return true;
    }
    return false;
  }

  function etape() {
    mission.appels_modele += 1;
    if (phase === "recherche") {
      mission.action_en_cours = "search_web";
      mission.requetes_reseau += 1;
      consommer();
      journaliser("recherche", `Action : recherche web « ${mission.sujet} » (k=5) → 5 résultats`);
      mission.action_en_cours = null;
      phase = "ouvrir";
      return;
    }
    if (phase === "ouvrir") {
      const domaine = mission.domaines[compteur % mission.domaines.length];
      const url = `https://${domaine}${CHEMINS[compteur % CHEMINS.length]}`;
      compteur += 1;
      if (compteur % 4 === 3) urlsEnEchec.add(url);
      source = { url, titre: "", statut: "en_cours", erreur: null };
      mission.sources.push(source);
      mission.action_en_cours = "read_page";
      mission.requetes_reseau += 1;
      consommer();
      tentatives.set(url, 1);
      journaliser("lecture", `Tentative 1/2 : ${url}`);
      phase = "resoudre";
      return;
    }
    if (phase === "resoudre") {
      if (urlsEnEchec.has(source.url)) {
        if (tentatives.get(source.url) === 1) {
          tentatives.set(source.url, 2);
          mission.requetes_reseau += 1;
          consommer();
          journaliser("erreur", `Erreur lecture d'une page : délai dépassé (tentative 1/2)`);
          journaliser("lecture", `Tentative 2/2 : ${source.url}`);
          return;
        }
        source.statut = "echec";
        source.erreur = "timeout";
        journaliser("erreur", `Erreur lecture d'une page : délai dépassé — deux tentatives, abandon`);
      } else {
        source.statut = "ok";
        source.titre = `Page ${compteur} (simulée)`;
        okDepuisConstat += 1;
        journaliser("lecture", `Page conservée : ${source.url}`);
      }
      mission.action_en_cours = null;
      phase = okDepuisConstat >= 2 ? "constat" : compteur % 3 === 0 ? "recherche" : "ouvrir";
      return;
    }
    if (phase === "constat") {
      const preuves = mission.sources
        .filter((s) => s.statut === "ok")
        .slice(-2)
        .map((s, i) => ({ url: s.url, source_id: null, extrait: EXTRAITS[(mission.constats.length + i) % EXTRAITS.length] }));
      const n = mission.constats.length;
      mission.action_en_cours = "save_finding";
      mission.constats.push({
        id: `c${n + 1}`,
        titre: TITRES[n % TITRES.length],
        resume: RESUMES[n % RESUMES.length],
        interet_developpeur: IMPACTS[n % IMPACTS.length],
        preuves,
        date_evenement: new Date(Date.now() - (n + 1) * 86400000).toISOString().slice(0, 10),
        statut_date: "in_window",
        confiance: preuves.length > 1 ? "corroborated" : "single_source",
        reserves: n % 2 === 1 ? ["Annonce non encore reprise dans la documentation."] : [],
      });
      consommer();
      journaliser("constat", `Constat nouveau #c${n + 1}, ${preuves.length} preuve(s)`);
      mission.action_en_cours = null;
      okDepuisConstat = 0;
      phase = "ouvrir";
    }
  }

  function avancer() {
    if (!mission) return;
    if (mission.statut === "pending") {
      mission.statut = "running";
      journaliser("etat", "Démarrage de l'agent");
      return;
    }
    if (mission.statut === "stopping") {
      ticksArret += 1;
      if (ticksArret >= 2) {
        mission.statut = "stopped";
        mission.action_en_cours = null;
        journaliser("etat", `Fin de mission : arrêté (manuel), budget restant ${mission.budget.restant}`);
      }
      return;
    }
    if (mission.statut !== "running") return;
    mission.temps.ecoule_s = Math.min(mission.temps.max_s, mission.temps.ecoule_s + 3);
    if (terminerSiLimiteAtteinte()) return;
    etape();
    terminerSiLimiteAtteinte();
  }

  return {
    async creerMission(valeurs) {
      await attendre();
      mission = {
        id: `demo-${Date.now().toString(36)}`,
        statut: "pending",
        sujet: valeurs.sujet,
        domaines: valeurs.domaines,
        budget: { restant: valeurs.budget, max: valeurs.budget },
        temps: { ecoule_s: 0, max_s: valeurs.duree * 60 },
        action_en_cours: null,
        appels_modele: 0,
        requetes_reseau: 0,
        sources: [],
        constats: [],
        journal: [],
        erreur: null,
      };
      phase = "recherche";
      source = null;
      compteur = 0;
      okDepuisConstat = 0;
      ticksArret = 0;
      urlsEnEchec.clear();
      tentatives.clear();
      journaliser("etat", `Mission créée : « ${mission.sujet} », ${mission.domaines.length} domaine(s), budget ${mission.budget.max}, durée ${valeurs.duree} min`);
      return copie();
    },

    async obtenirMission() {
      await attendre();
      avancer();
      return copie();
    },

    async arreterMission() {
      await attendre();
      if (mission.statut === "pending" || mission.statut === "running") {
        mission.statut = "stopping";
        ticksArret = 0;
        journaliser("etat", "Arrêt demandé par l'opérateur : plus aucune nouvelle action");
      }
      return copie();
    },
  };
}

const api = MODE_DEMO ? creerSimulateur() : apiReel;

// ---------- Éléments ----------

const $ = (id) => document.getElementById(id);

const els = {
  ecranAccueil: $("ecran-accueil"),
  ecranRecherche: $("ecran-recherche"),
  topbarMission: $("topbar-mission"),
  topbarSujet: $("topbar-sujet"),
  etatBadge: $("etat-badge"),
  boutonTheme: $("bouton-theme"),
  barreActivite: $("barre-activite"),
  toasts: $("toasts"),

  formLancement: $("form-lancement"),
  champSujet: $("champ-sujet"),
  champDomaine: $("champ-domaine"),
  chipsDomaines: $("chips-domaines"),
  domainesCompteur: $("domaines-compteur"),
  erreurDomaine: $("erreur-domaine"),
  champBudget: $("champ-budget"),
  curseurBudget: $("curseur-budget"),
  champDuree: $("champ-duree"),
  curseurDuree: $("curseur-duree"),
  champJeton: $("champ-jeton"),
  presets: Array.from(document.querySelectorAll(".preset")),
  resumeMission: $("resume-mission"),
  erreurFormulaire: $("erreur-formulaire"),
  boutonLancer: $("bouton-lancer"),
  iconeChargementLancer: $("bouton-lancer").querySelector(".icone-chargement"),
  texteBoutonLancer: $("bouton-lancer").querySelector(".bouton-texte"),

  bandeauDemo: $("bandeau-demo"),
  bandeauConnexion: $("bandeau-connexion"),
  bandeauErreur: $("bandeau-erreur"),
  etatBadgeGrand: $("etat-badge-grand"),
  etatDescription: $("etat-description"),
  actionEnCours: $("action-en-cours"),
  derniereAction: $("derniere-action"),
  statSourcesOk: $("stat-sources-ok"),
  statSourcesEchec: $("stat-sources-echec"),
  statConstats: $("stat-constats"),
  statAppelsModele: $("stat-appels-modele"),
  statRequetesReseau: $("stat-requetes-reseau"),
  boutonArret: $("bouton-arret"),
  iconeArret: $("bouton-arret").querySelector("use"),
  texteArret: $("bouton-arret").querySelector(".bouton-texte"),
  boutonNouvelleRecherche: $("bouton-nouvelle-recherche"),

  anneauBudgetBloc: $("anneau-budget-bloc"),
  anneauBudgetCercle: $("anneau-budget-cercle"),
  anneauBudgetValeur: $("anneau-budget-valeur"),
  anneauBudgetDetail: $("anneau-budget-detail"),
  anneauTempsBloc: $("anneau-temps-bloc"),
  anneauTempsCercle: $("anneau-temps-cercle"),
  anneauTempsValeur: $("anneau-temps-valeur"),
  anneauTempsDetail: $("anneau-temps-detail"),

  sourcesCompteur: $("sources-compteur"),
  sourcesVide: $("sources-vide"),
  listeSources: $("liste-sources"),
  synthesePartielle: $("synthese-partielle"),
  syntheseVide: $("synthese-vide"),
  syntheseVideTexte: $("synthese-vide-texte"),
  listeConstats: $("liste-constats"),

  carteJournal: $("carte-journal"),
  journalCompteur: $("journal-compteur"),
  journalFiltres: $("journal-filtres"),
  journalSuivre: $("journal-suivre"),
  boutonCopierJournal: $("bouton-copier-journal"),
  boutonExporter: $("bouton-exporter"),
  boutonJournalReplier: $("bouton-journal-replier"),
  journalVide: $("journal-vide"),
  journalListe: $("journal-liste"),
};

// ---------- Utilitaires ----------

const NS_SVG = "http://www.w3.org/2000/svg";

function icone(nom) {
  const svg = document.createElementNS(NS_SVG, "svg");
  svg.setAttribute("class", "icone");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(NS_SVG, "use");
  use.setAttribute("href", `#i-${nom}`);
  svg.appendChild(use);
  return svg;
}

function relancerAnimation(el, classe) {
  el.classList.remove(classe);
  void el.offsetWidth; // force un reflow, sinon le navigateur ne rejoue pas l'animation
  el.classList.add(classe);
}

function definirTexteAvecEclat(el, texte) {
  if (el.textContent === texte) return;
  el.textContent = texte;
  relancerAnimation(el, "valeur-maj");
}

function formaterTemps(secondes) {
  const s = Math.max(0, Math.round(secondes));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function hoteEtChemin(url) {
  try {
    const u = new URL(url);
    const chemin = u.pathname + u.search;
    return { hote: u.hostname, chemin: chemin === "/" ? "" : chemin };
  } catch {
    return { hote: String(url), chemin: "" };
  }
}

function urlSure(url) {
  return /^https:\/\//i.test(url);
}

// ---------- Thème ----------

const CLE_THEME = "lockin-theme";

function appliquerTheme(theme) {
  document.documentElement.dataset.theme = theme;
  els.boutonTheme.setAttribute("aria-label", theme === "dark" ? "Passer en thème clair" : "Passer en thème sombre");
}

function themeInitial() {
  try {
    const stocke = localStorage.getItem(CLE_THEME);
    if (stocke === "light" || stocke === "dark") return stocke;
  } catch {
    // stockage indisponible : on suit le système
  }
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

appliquerTheme(themeInitial());

els.boutonTheme.addEventListener("click", () => {
  const suivant = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  appliquerTheme(suivant);
  try {
    localStorage.setItem(CLE_THEME, suivant);
  } catch {
    // stockage indisponible : le choix vaut pour cette page seulement
  }
});

// ---------- Notifications ----------

function afficherToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  els.toasts.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("toast-sortie");
    toast.addEventListener("animationend", () => toast.remove(), { once: true });
  }, 4000);
}

// ---------- Effet de clic (ondulation) ----------

function declencherOndulation(cible, evenement) {
  const precedente = cible.querySelector(":scope > .ondulation");
  if (precedente) precedente.remove();

  const rect = cible.getBoundingClientRect();
  const taille = Math.max(rect.width, rect.height) * 1.6;
  const x = evenement.clientX - rect.left;
  const y = evenement.clientY - rect.top;

  const onde = document.createElement("span");
  onde.className = "ondulation";
  onde.style.width = `${taille}px`;
  onde.style.height = `${taille}px`;
  onde.style.left = `${x - taille / 2}px`;
  onde.style.top = `${y - taille / 2}px`;

  cible.appendChild(onde);
  onde.addEventListener("animationend", () => onde.remove(), { once: true });
}

document.addEventListener("pointerdown", (evenement) => {
  const cible = evenement.target.closest(".ondule");
  if (!cible || cible.disabled) return;
  declencherOndulation(cible, evenement);
});

// ---------- Formulaire : domaines ----------

let domaines = [];

function normaliserDomaine(brut) {
  return brut
    .trim()
    .toLowerCase()
    .replace(/^[a-z]+:\/\//, "")
    .split(/[/?#]/)[0]
    .replace(/:\d+$/, "")
    .replace(/\.$/, "");
}

function afficherErreurDomaine(message) {
  els.erreurDomaine.textContent = message;
  els.erreurDomaine.hidden = false;
  relancerAnimation(els.chipsDomaines, "secousse");
}

function masquerErreurDomaine() {
  els.erreurDomaine.hidden = true;
  els.chipsDomaines.classList.remove("secousse");
}

function creerChip(domaine) {
  const chip = document.createElement("span");
  chip.className = "chip";
  chip.dataset.domaine = domaine;

  const texte = document.createElement("span");
  texte.textContent = domaine;

  const retirer = document.createElement("button");
  retirer.type = "button";
  retirer.className = "chip-retirer";
  retirer.setAttribute("aria-label", `Retirer ${domaine}`);
  retirer.appendChild(icone("croix"));
  retirer.addEventListener("click", () => retirerDomaine(domaine));

  chip.append(texte, retirer);
  return chip;
}

function ajouterDomaine(brut) {
  const domaine = normaliserDomaine(brut);
  if (!domaine) return false;

  let erreur = null;
  if (domaines.length >= MAX_DOMAINES) erreur = `Au plus ${MAX_DOMAINES} domaines autorisés.`;
  else if (!MOTIF_DOMAINE.test(domaine)) erreur = "Indiquer un nom de domaine public, comme www.exemple.org, sans http:// ni chemin.";
  else if (domaines.includes(domaine)) erreur = "Ce domaine est déjà dans la liste.";

  if (erreur) {
    afficherErreurDomaine(erreur);
    return false;
  }

  domaines.push(domaine);
  els.chipsDomaines.insertBefore(creerChip(domaine), els.champDomaine);
  els.champDomaine.value = "";
  masquerErreurDomaine();
  mettreAJourFormulaire();
  return true;
}

function retirerDomaine(domaine) {
  const index = domaines.indexOf(domaine);
  if (index === -1) return;
  domaines.splice(index, 1);

  const chip = els.chipsDomaines.querySelector(`.chip[data-domaine="${CSS.escape(domaine)}"]`);
  if (chip) {
    chip.classList.add("chip-sortie");
    chip.addEventListener("animationend", () => chip.remove(), { once: true });
  }
  masquerErreurDomaine();
  mettreAJourFormulaire();
  els.champDomaine.focus();
}

els.champDomaine.addEventListener("keydown", (evenement) => {
  if (evenement.key === "Enter" || evenement.key === ",") {
    evenement.preventDefault();
    ajouterDomaine(els.champDomaine.value);
  } else if (evenement.key === "Backspace" && els.champDomaine.value === "" && domaines.length > 0) {
    retirerDomaine(domaines[domaines.length - 1]);
  }
});

els.champDomaine.addEventListener("input", () => {
  const valeur = els.champDomaine.value;
  if (/[\s,]/.test(valeur)) {
    const morceaux = valeur.split(/[\s,]+/);
    morceaux.slice(0, -1).forEach((morceau) => ajouterDomaine(morceau));
    els.champDomaine.value = morceaux[morceaux.length - 1];
  } else {
    masquerErreurDomaine();
  }
});

els.champDomaine.addEventListener("blur", () => {
  if (els.champDomaine.value.trim()) ajouterDomaine(els.champDomaine.value);
});

els.chipsDomaines.addEventListener("click", (evenement) => {
  if (evenement.target === els.chipsDomaines) els.champDomaine.focus();
});

// ---------- Formulaire : curseurs et réglages rapides ----------

function lierCurseur(curseur, nombre) {
  const majRemplissage = () => {
    const min = Number(curseur.min);
    const max = Number(curseur.max);
    const valeur = Math.min(max, Math.max(min, Number(curseur.value)));
    curseur.style.setProperty("--pct", `${((valeur - min) / (max - min)) * 100}%`);
  };

  curseur.addEventListener("input", () => {
    nombre.value = curseur.value;
    majRemplissage();
    mettreAJourFormulaire();
  });

  nombre.addEventListener("input", () => {
    if (nombre.value !== "") curseur.value = nombre.value;
    majRemplissage();
    mettreAJourFormulaire();
  });

  majRemplissage();
  return majRemplissage;
}

const majCurseurBudget = lierCurseur(els.curseurBudget, els.champBudget);
const majCurseurDuree = lierCurseur(els.curseurDuree, els.champDuree);

for (const preset of els.presets) {
  preset.addEventListener("click", () => {
    els.champBudget.value = preset.dataset.budget;
    els.curseurBudget.value = preset.dataset.budget;
    els.champDuree.value = preset.dataset.duree;
    els.curseurDuree.value = preset.dataset.duree;
    majCurseurBudget();
    majCurseurDuree();
    mettreAJourFormulaire();
  });
}

// ---------- Formulaire : validation et résumé ----------

function lireFormulaire() {
  return {
    sujet: els.champSujet.value.trim(),
    domaines: [...domaines],
    budget: Number(els.champBudget.value),
    duree: Number(els.champDuree.value),
    jeton: els.champJeton.value.trim(),
  };
}

function validerFormulaire() {
  const valeurs = lireFormulaire();
  const erreurs = [];

  if (!valeurs.sujet) erreurs.push("Le sujet est obligatoire.");
  else if (valeurs.sujet.length > MAX_SUJET) erreurs.push(`Le sujet dépasse ${MAX_SUJET} caractères.`);
  if (valeurs.domaines.length === 0) erreurs.push("Ajoutez au moins un domaine autorisé.");
  if (!Number.isInteger(valeurs.budget) || valeurs.budget < 1 || valeurs.budget > MAX_BUDGET) {
    erreurs.push(`Le budget d'actions doit être un entier entre 1 et ${MAX_BUDGET}.`);
  }
  if (!Number.isInteger(valeurs.duree) || valeurs.duree < 1 || valeurs.duree > MAX_DUREE) {
    erreurs.push(`La durée maximale doit être un entier entre 1 et ${MAX_DUREE} minutes.`);
  }
  if (!MODE_DEMO && valeurs.jeton.length < LONGUEUR_MIN_JETON) {
    erreurs.push(`Le jeton opérateur est requis (${LONGUEUR_MIN_JETON} caractères minimum).`);
  }

  return { ...valeurs, erreurs, valide: erreurs.length === 0 };
}

function mettreAJourResume(valeurs) {
  const { sujet, domaines: liste, budget, duree } = valeurs;
  if (!sujet && liste.length === 0) {
    els.resumeMission.replaceChildren();
    return;
  }

  const fort = (texte) => {
    const el = document.createElement("strong");
    el.textContent = texte;
    return el;
  };

  const nbDomaines = liste.length;
  els.resumeMission.replaceChildren(
    "L'agent explorera ",
    fort(nbDomaines === 0 ? "aucun domaine pour l'instant" : `${nbDomaines} domaine${nbDomaines > 1 ? "s" : ""}`),
    " sur « ",
    fort(sujet || "sujet à préciser"),
    " », avec au plus ",
    fort(`${budget} action${budget > 1 ? "s" : ""}`),
    " et ",
    fort(`${duree} min`),
    ". Il s'arrête au premier des deux atteint."
  );
}

function mettreAJourPresets(valeurs) {
  for (const preset of els.presets) {
    const actif = Number(preset.dataset.budget) === valeurs.budget && Number(preset.dataset.duree) === valeurs.duree;
    preset.classList.toggle("est-actif", actif);
  }
}

function mettreAJourFormulaire() {
  const valeurs = validerFormulaire();
  els.boutonLancer.disabled = !valeurs.valide || els.boutonLancer.classList.contains("chargement");
  els.erreurFormulaire.hidden = true;
  els.domainesCompteur.textContent = `${valeurs.domaines.length} / ${MAX_DOMAINES}`;
  mettreAJourResume(valeurs);
  mettreAJourPresets(valeurs);
}

function definirChargement(actif) {
  els.boutonLancer.classList.toggle("chargement", actif);
  els.iconeChargementLancer.hidden = !actif;
  els.texteBoutonLancer.textContent = actif ? "Lancement…" : "Lancer la recherche";
  els.boutonLancer.disabled = actif || !validerFormulaire().valide;
}

function reinitialiserFormulaire() {
  els.formLancement.reset();
  domaines = [];
  for (const chip of els.chipsDomaines.querySelectorAll(".chip")) chip.remove();
  masquerErreurDomaine();
  els.champJeton.value = jetonMemoire;
  majCurseurBudget();
  majCurseurDuree();
  mettreAJourFormulaire();
}

els.champSujet.addEventListener("input", mettreAJourFormulaire);
els.champJeton.addEventListener("input", mettreAJourFormulaire);

els.formLancement.addEventListener("submit", async (evenement) => {
  evenement.preventDefault();
  if (els.champDomaine.value.trim()) ajouterDomaine(els.champDomaine.value);

  const valeurs = validerFormulaire();
  if (!valeurs.valide) {
    els.erreurFormulaire.textContent = valeurs.erreurs[0];
    els.erreurFormulaire.hidden = false;
    return;
  }

  jetonMemoire = valeurs.jeton;
  definirChargement(true);
  try {
    const mission = await api.creerMission(valeurs);
    demarrerSuiviMission(mission);
  } catch (erreur) {
    const message = erreur instanceof TypeError
      ? "Le service ne répond pas. Vérifiez que le serveur Lockin est lancé."
      : erreur.message || "Impossible de lancer la recherche.";
    els.erreurFormulaire.textContent = message;
    els.erreurFormulaire.hidden = false;
    afficherToast(message, "danger");
  } finally {
    definirChargement(false);
  }
});

// ---------- Tableau de bord ----------

const CIRCONFERENCE_ANNEAU = 2 * Math.PI * 68;
for (const cercle of [els.anneauBudgetCercle, els.anneauTempsCercle]) {
  cercle.style.strokeDasharray = `${CIRCONFERENCE_ANNEAU}`;
  cercle.style.strokeDashoffset = `${CIRCONFERENCE_ANNEAU}`;
}

let missionCourante = null;
let statutPrecedent = null;
let derniereReception = 0;
let echecsConsecutifs = 0;
let lectureEnCours = false;
let intervalleId = null;
let horlogeId = null;

function definirAnneau(cercle, ratio) {
  const r = Math.min(1, Math.max(0, ratio));
  cercle.style.strokeDashoffset = `${CIRCONFERENCE_ANNEAU * (1 - r)}`;
}

// Synchronise une liste DOM avec un tableau de données : seules les entrées
// nouvelles sont créées (et animées), les autres sont mises à jour en place,
// les disparues sont retirées. Indispensable avec un rafraîchissement toutes
// les secondes, sinon le journal clignote et le défilement saute.
function synchroniserListe(conteneur, items, cleDe, creerNoeud, mettreAJourNoeud) {
  const existants = new Map();
  for (const enfant of conteneur.children) existants.set(enfant.dataset.cle, enfant);

  const clesVues = new Set();
  items.forEach((item, index) => {
    const cle = String(cleDe(item, index));
    clesVues.add(cle);
    const existant = existants.get(cle);
    if (existant) {
      mettreAJourNoeud(existant, item);
    } else {
      const noeud = creerNoeud(item);
      noeud.dataset.cle = cle;
      noeud.classList.add("entree-nouvelle");
      conteneur.appendChild(noeud);
    }
  });
  for (const [cle, noeud] of existants) if (!clesVues.has(cle)) noeud.remove();
}

// Sources

const ICONES_STATUT_SOURCE = { ok: "ok", en_cours: "chargement", echec: "croix" };
const LIBELLES_STATUT_SOURCE = { ok: "ok", en_cours: "en cours", echec: "échec" };

function creerNoeudSource(source) {
  const li = document.createElement("li");
  const ic = document.createElement("span");
  ic.className = "source-icone";
  const texte = document.createElement("span");
  texte.className = "source-texte";
  const hote = document.createElement("span");
  hote.className = "source-hote";
  const chemin = document.createElement("span");
  chemin.className = "source-chemin";
  texte.append(hote, chemin);
  const statut = document.createElement("span");
  statut.className = "source-statut";
  li.append(ic, texte, statut);
  mettreAJourNoeudSource(li, source);
  return li;
}

function mettreAJourNoeudSource(li, source) {
  const { hote, chemin } = hoteEtChemin(source.url);
  li.querySelector(".source-hote").textContent = source.titre || hote;
  li.querySelector(".source-chemin").textContent = source.titre ? hote + chemin : chemin;
  li.title = source.erreur ? `${source.url}\n${libelleErreur(source.erreur)}` : source.url;

  const ic = li.querySelector(".source-icone");
  const statut = li.querySelector(".source-statut");
  const empreinte = `${source.statut}|${source.erreur ?? ""}`;
  if (statut.dataset.empreinte !== empreinte) {
    statut.dataset.empreinte = empreinte;
    statut.dataset.statut = source.statut;
    ic.dataset.statut = source.statut;
    statut.textContent = LIBELLES_STATUT_SOURCE[source.statut] || source.statut;
    ic.replaceChildren(icone(ICONES_STATUT_SOURCE[source.statut] || "ok"));
    relancerAnimation(statut, "statut-maj");
  }
}

// Constats

function libelleDateConstat(constat) {
  const morceaux = [];
  if (constat.date_evenement) morceaux.push(constat.date_evenement);
  if (LIBELLES_STATUT_DATE[constat.statut_date]) morceaux.push(LIBELLES_STATUT_DATE[constat.statut_date]);
  return morceaux.join(" · ");
}

function creerLienSource(url, libelleRepli) {
  let lien;
  if (url && urlSure(url)) {
    lien = document.createElement("a");
    lien.href = url;
    lien.target = "_blank";
    lien.rel = "noopener noreferrer";
  } else {
    lien = document.createElement("span");
  }
  lien.className = "constat-source";
  lien.title = url || libelleRepli;
  lien.appendChild(icone("lien"));
  const libelle = document.createElement("span");
  if (url) {
    const { hote, chemin } = hoteEtChemin(url);
    libelle.textContent = hote + chemin;
  } else {
    libelle.textContent = libelleRepli;
  }
  lien.appendChild(libelle);
  return lien;
}

function creerNoeudConstat(constat) {
  const li = document.createElement("li");
  li.className = "constat";

  const entete = document.createElement("div");
  entete.className = "constat-entete";
  const titre = document.createElement("h3");
  titre.className = "constat-titre";
  titre.textContent = constat.titre || "Constat";
  entete.appendChild(titre);
  const confiance = LIBELLES_CONFIANCE[constat.confiance];
  if (confiance) {
    const etiquette = document.createElement("span");
    etiquette.className = `etiquette etiquette-${confiance[1]}`;
    etiquette.textContent = confiance[0];
    entete.appendChild(etiquette);
  }
  li.appendChild(entete);

  if (constat.resume) {
    const resume = document.createElement("p");
    resume.className = "constat-resume";
    resume.textContent = constat.resume;
    li.appendChild(resume);
  }

  if (constat.interet_developpeur) {
    const impact = document.createElement("p");
    impact.className = "constat-impact";
    impact.textContent = constat.interet_developpeur;
    li.appendChild(impact);
  }

  for (const preuve of constat.preuves || []) {
    const bloc = document.createElement("blockquote");
    bloc.className = "constat-preuve";
    if (preuve.extrait) {
      const extrait = document.createElement("p");
      extrait.className = "constat-extrait";
      extrait.textContent = `« ${preuve.extrait} »`;
      bloc.appendChild(extrait);
    }
    bloc.appendChild(creerLienSource(preuve.url, preuve.source_id ? `source ${preuve.source_id}` : "source inconnue"));
    li.appendChild(bloc);
  }

  const pied = document.createElement("div");
  pied.className = "constat-pied";
  if (constat.reserves && constat.reserves.length) {
    const reserves = document.createElement("p");
    reserves.className = "constat-reserves";
    reserves.textContent = `Réserves : ${constat.reserves.join(" · ")}`;
    pied.appendChild(reserves);
  }
  const date = libelleDateConstat(constat);
  if (date) {
    const el = document.createElement("span");
    el.className = "constat-date";
    el.textContent = date;
    pied.appendChild(el);
  }
  if (pied.childNodes.length) li.appendChild(pied);

  return li;
}

// Journal

function creerNoeudJournal(entree) {
  const li = document.createElement("li");
  li.dataset.type = entree.type || "interne";

  const point = document.createElement("span");
  point.className = "journal-point";
  const heure = document.createElement("time");
  heure.className = "journal-heure";
  heure.textContent = entree.ts || "";
  const message = document.createElement("span");
  message.className = "journal-message";
  message.textContent = entree.message || "";
  const budget = document.createElement("span");
  budget.className = "journal-budget";
  if (entree.budget_restant !== undefined && entree.budget_restant !== null) {
    budget.textContent = `reste ${entree.budget_restant}`;
  }

  li.append(point, heure, message, budget);
  return li;
}

function ligneJournal(entree) {
  const seq = entree.seq !== undefined && entree.seq !== null ? `#${String(entree.seq).padStart(3, "0")}  ` : "";
  const budget = entree.budget_restant !== undefined && entree.budget_restant !== null ? `  [reste ${entree.budget_restant}]` : "";
  return `${seq}${entree.ts}  ${entree.message}${budget}`;
}

// Temps : entre deux réponses du serveur, on fait avancer l'horloge en local
// pour que l'anneau reste fluide. La valeur du serveur reprend la main à
// chaque rafraîchissement.

function tempsEcouleEstime() {
  const temps = missionCourante.temps || { ecoule_s: 0, max_s: 0 };
  let ecoule = temps.ecoule_s || 0;
  if ((missionCourante.statut === "running" || missionCourante.statut === "stopping") && derniereReception) {
    ecoule += (Date.now() - derniereReception) / 1000;
  }
  const max = temps.max_s || 0;
  if (max) ecoule = Math.min(ecoule, max);
  return { ecoule, max };
}

function rendreTemps() {
  if (!missionCourante) return;
  const { ecoule, max } = tempsEcouleEstime();
  els.anneauTempsValeur.textContent = `${formaterTemps(ecoule)} / ${formaterTemps(max)}`;
  els.anneauTempsDetail.textContent = max ? `échéance ${formaterTemps(max)} · reste ${formaterTemps(max - ecoule)}` : "échéance : —";
  definirAnneau(els.anneauTempsCercle, max ? ecoule / max : 0);
}

function demarrerHorloge() {
  if (horlogeId === null) horlogeId = setInterval(rendreTemps, 250);
}

function arreterHorloge() {
  if (horlogeId !== null) {
    clearInterval(horlogeId);
    horlogeId = null;
  }
}

// État et actions

function rendreBoutonArret(statut, envoiEnCours = false) {
  const bouton = els.boutonArret;
  bouton.hidden = !ETATS_ACTIFS.has(statut);
  const occupe = envoiEnCours || statut === "stopping";
  bouton.disabled = occupe;
  bouton.classList.toggle("chargement", occupe);
  els.iconeArret.setAttribute("href", occupe ? "#i-chargement" : "#i-stop");
  els.texteArret.textContent = envoiEnCours ? "Envoi de l'arrêt…" : statut === "stopping" ? "Arrêt en cours…" : "Arrêter l'agent";
}

const NOTIFICATIONS_ETAT = {
  running: ["L'agent a démarré.", "info"],
  stopping: ["Arrêt reçu par le serveur : plus aucune nouvelle action.", "attention"],
  stopped: ["Agent arrêté. L'état est figé et consultable.", "succes"],
  completed: ["Mission terminée.", "succes"],
  budget_exhausted: ["Budget épuisé, mission arrêtée. Les résultats sont conservés.", "attention"],
  deadline_reached: ["Durée maximale atteinte, mission arrêtée. Les résultats sont conservés.", "attention"],
  failed: ["La mission a échoué. Consultez le journal.", "danger"],
};

function rendreMission(mission) {
  const statut = mission.statut;
  const libelle = LIBELLES_ETAT[statut] || statut;
  for (const badge of [els.etatBadge, els.etatBadgeGrand]) {
    badge.textContent = libelle;
    badge.dataset.etat = statut;
  }
  els.etatDescription.textContent = DESCRIPTIONS_ETAT[statut] || "";

  const actif = ETATS_ACTIFS.has(statut);
  els.barreActivite.classList.toggle("barre-activite-active", actif);
  els.anneauBudgetBloc.classList.toggle("anneau-actif", actif);
  els.anneauTempsBloc.classList.toggle("anneau-actif", actif);

  const budget = mission.budget || { restant: 0, max: 0 };
  const utilise = Math.max(0, budget.max - budget.restant);
  definirTexteAvecEclat(els.anneauBudgetValeur, `${utilise} / ${budget.max}`);
  els.anneauBudgetDetail.textContent = `restant : ${budget.restant} action${budget.restant > 1 ? "s" : ""}`;
  definirAnneau(els.anneauBudgetCercle, budget.max ? utilise / budget.max : 0);

  rendreTemps();

  els.actionEnCours.textContent = mission.action_en_cours
    ? LIBELLES_ACTION[mission.action_en_cours] || mission.action_en_cours
    : actif ? "décision du modèle en cours" : "—";

  const sources = mission.sources || [];
  synchroniserListe(els.listeSources, sources, (s) => s.url, creerNoeudSource, mettreAJourNoeudSource);
  els.sourcesVide.hidden = sources.length !== 0;
  els.sourcesCompteur.textContent = String(sources.length);
  const nbOk = sources.filter((s) => s.statut === "ok").length;
  const nbEchec = sources.filter((s) => s.statut === "echec").length;
  definirTexteAvecEclat(els.statSourcesOk, String(nbOk));
  definirTexteAvecEclat(els.statSourcesEchec, String(nbEchec));
  definirTexteAvecEclat(els.statAppelsModele, String(mission.appels_modele ?? 0));
  definirTexteAvecEclat(els.statRequetesReseau, String(mission.requetes_reseau ?? 0));

  const constats = mission.constats || [];
  synchroniserListe(els.listeConstats, constats, (c, i) => c.id ?? i, creerNoeudConstat, () => {});
  els.syntheseVide.hidden = constats.length !== 0;
  if (constats.length === 0) {
    els.syntheseVideTexte.textContent = ETATS_TERMINAUX.has(statut)
      ? `${mission.synthese || "Aucune nouveauté pertinente trouvée."} Ce n'est pas une panne : ne rien avoir trouvé est un résultat valide.`
      : mission.synthese || "Aucun constat pour l'instant.";
  }
  definirTexteAvecEclat(els.statConstats, String(constats.length));
  const partielle = mission.partielle ?? ((statut !== "completed" && statut !== "pending") || nbEchec > 0);
  els.synthesePartielle.hidden = !partielle;

  const journal = mission.journal || [];
  synchroniserListe(els.journalListe, journal, (e, i) => e.seq ?? i, creerNoeudJournal, () => {});
  els.journalVide.hidden = journal.length !== 0;
  els.journalCompteur.textContent = String(journal.length);
  if (els.journalSuivre.checked) els.journalListe.scrollTop = els.journalListe.scrollHeight;
  const derniere = journal[journal.length - 1];
  els.derniereAction.textContent = derniere ? derniere.message : "—";

  if (statut === "failed") {
    els.bandeauErreur.textContent = mission.erreur ? `Erreur : ${mission.erreur.message}` : "Erreur : panne bloquante.";
    els.bandeauErreur.hidden = false;
  } else {
    els.bandeauErreur.hidden = true;
  }

  rendreBoutonArret(statut);
  els.boutonNouvelleRecherche.hidden = !ETATS_TERMINAUX.has(statut);

  if (statutPrecedent && statutPrecedent !== statut && NOTIFICATIONS_ETAT[statut]) {
    afficherToast(...NOTIFICATIONS_ETAT[statut]);
  }
  statutPrecedent = statut;

  if (ETATS_TERMINAUX.has(statut)) {
    arreterRafraichissement();
    arreterHorloge();
    rendreTemps();
  }
}

function demarrerSuiviMission(mission) {
  missionCourante = mission;
  statutPrecedent = null;
  derniereReception = Date.now();
  echecsConsecutifs = 0;

  els.listeSources.replaceChildren();
  els.listeConstats.replaceChildren();
  els.journalListe.replaceChildren();
  els.bandeauConnexion.hidden = true;
  els.bandeauDemo.hidden = !MODE_DEMO;
  els.topbarSujet.textContent = mission.sujet;
  els.topbarMission.hidden = false;
  els.etatBadge.hidden = false;

  els.ecranAccueil.hidden = true;
  els.ecranRecherche.hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });

  rendreMission(mission);
  if (!ETATS_TERMINAUX.has(mission.statut)) {
    demarrerRafraichissement();
    demarrerHorloge();
  }
}

function revenirAccueil() {
  arreterRafraichissement();
  arreterHorloge();
  missionCourante = null;
  statutPrecedent = null;

  els.barreActivite.classList.remove("barre-activite-active");
  els.topbarMission.hidden = true;
  els.etatBadge.hidden = true;
  els.ecranRecherche.hidden = true;
  els.ecranAccueil.hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });

  reinitialiserFormulaire();
  els.champSujet.focus();
}

// ---------- Rafraîchissement ----------

function demarrerRafraichissement() {
  arreterRafraichissement();
  intervalleId = setInterval(rafraichirMission, INTERVALLE_RAFRAICHISSEMENT_MS);
}

function arreterRafraichissement() {
  if (intervalleId !== null) {
    clearInterval(intervalleId);
    intervalleId = null;
  }
}

async function rafraichirMission() {
  if (!missionCourante || lectureEnCours) return;
  const identifiant = missionCourante.id;
  lectureEnCours = true;
  try {
    const mission = await api.obtenirMission(identifiant);
    if (!missionCourante || missionCourante.id !== identifiant) return;
    missionCourante = mission;
    derniereReception = Date.now();
    echecsConsecutifs = 0;
    els.bandeauConnexion.hidden = true;
    rendreMission(mission);
  } catch {
    echecsConsecutifs += 1;
    if (echecsConsecutifs >= 2) els.bandeauConnexion.hidden = false;
  } finally {
    lectureEnCours = false;
  }
}

// ---------- Actions du tableau de bord ----------

els.boutonArret.addEventListener("click", async () => {
  if (!missionCourante) return;
  const identifiant = missionCourante.id;
  rendreBoutonArret(missionCourante.statut, true);
  try {
    const mission = await api.arreterMission(identifiant);
    if (!missionCourante || missionCourante.id !== identifiant) return;
    missionCourante = mission;
    derniereReception = Date.now();
    rendreMission(mission);
  } catch (erreur) {
    if (missionCourante) rendreBoutonArret(missionCourante.statut);
    afficherToast(`L'ordre d'arrêt n'a pas pu être transmis : ${erreur.message || "réessayez."}`, "danger");
  }
});

els.boutonNouvelleRecherche.addEventListener("click", revenirAccueil);

els.journalFiltres.addEventListener("click", (evenement) => {
  const bouton = evenement.target.closest(".filtre");
  if (!bouton) return;
  for (const filtre of els.journalFiltres.querySelectorAll(".filtre")) {
    filtre.classList.toggle("est-actif", filtre === bouton);
  }
  els.journalListe.dataset.filtre = bouton.dataset.filtre;
});

els.journalListe.addEventListener("scroll", () => {
  const liste = els.journalListe;
  els.journalSuivre.checked = liste.scrollHeight - liste.scrollTop - liste.clientHeight < 8;
});

els.journalSuivre.addEventListener("change", () => {
  if (els.journalSuivre.checked) els.journalListe.scrollTop = els.journalListe.scrollHeight;
});

els.boutonCopierJournal.addEventListener("click", async () => {
  const lignes = ((missionCourante && missionCourante.journal) || []).map(ligneJournal);
  try {
    await navigator.clipboard.writeText(lignes.join("\n"));
    afficherToast(`Journal copié (${lignes.length} ligne${lignes.length > 1 ? "s" : ""}).`, "succes");
  } catch {
    afficherToast("Impossible d'accéder au presse-papiers.", "danger");
  }
});

els.boutonExporter.addEventListener("click", () => {
  if (!missionCourante) return;
  const blob = new Blob([JSON.stringify(missionCourante, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const lien = document.createElement("a");
  lien.href = url;
  lien.download = `lockin-mission-${missionCourante.id || "export"}.json`;
  document.body.appendChild(lien);
  lien.click();
  lien.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  afficherToast("Mission exportée en JSON.", "succes");
});

els.boutonJournalReplier.addEventListener("click", () => {
  const repliee = els.carteJournal.classList.toggle("est-repliee");
  els.boutonJournalReplier.setAttribute("aria-expanded", String(!repliee));
  els.boutonJournalReplier.setAttribute("aria-label", repliee ? "Déplier le journal" : "Replier le journal");
});

// ---------- Initialisation ----------

els.champJeton.closest(".champ").hidden = MODE_DEMO;
mettreAJourFormulaire();
if (MODE_DEMO) afficherToast("Mode démonstration : données simulées, aucun appel réseau.", "attention");
