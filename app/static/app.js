"use strict";

/**
 * Contrat API assumé pour ce socle, en attendant API.md fourni par Codex.
 * À aligner avec Adam dès que le contrat réel est publié — seul l'objet
 * `apiReel` ci-dessous devrait avoir besoin de changer.
 *
 *   POST /api/missions
 *     body:  { sujet, domaines: string[], budget_max, duree_max_minutes }
 *     resp:  Mission
 *
 *   GET /api/missions/:id
 *     resp:  Mission
 *
 *   POST /api/missions/:id/arret
 *     resp:  Mission
 *
 *   Mission = {
 *     id, statut,               // pending | running | stopping | stopped
 *                                // | completed | budget_exhausted
 *                                // | deadline_reached | failed
 *     sujet, domaines: string[],
 *     budget: { restant, max },
 *     temps:  { ecoule_s, max_s },
 *     sources:  [{ url, statut: "ok" | "en_cours" | "abandon", tentatives? }],
 *     constats: [{ id, titre, resume, sources: string[],
 *                  interet_developpeur?, confiance?, date_evenement?, statut_date? }],
 *     journal:  [{ ts, message, type?, budget_restant? }],
 *     erreur:   { code, message } | null
 *   }
 *
 * Les champs marqués `?` sont facultatifs : l'interface les affiche s'ils
 * sont présents et s'en passe sinon.
 */

const MODE_DEMO = new URLSearchParams(location.search).has("demo");
const INTERVALLE_RAFRAICHISSEMENT_MS = 1000;
const MAX_DOMAINES = 5;
const MOTIF_DOMAINE = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/i;

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

// ---------- API réelle ----------

const apiReel = {
  async creerMission(payload) {
    const reponse = await fetch("/api/missions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!reponse.ok) throw new Error("echec_creation");
    return reponse.json();
  },

  async obtenirMission(id) {
    const reponse = await fetch(`/api/missions/${encodeURIComponent(id)}`);
    if (!reponse.ok) throw new Error("echec_lecture");
    return reponse.json();
  },

  async arreterMission(id) {
    const reponse = await fetch(`/api/missions/${encodeURIComponent(id)}/arret`, { method: "POST" });
    if (!reponse.ok) throw new Error("echec_arret");
    return reponse.json();
  },
};

// ---------- Simulateur (mode démo, `?demo` dans l'URL) ----------
// Données simulées dans le navigateur, sans aucun appel réseau. Sert à
// regarder l'interface avant que le backend existe. Jamais actif par défaut,
// et un bandeau l'annonce à l'écran : ce n'est pas une démonstration.

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

  let mission = null;
  let phase = "recherche";
  let source = null;
  let compteur = 0;
  let okDepuisConstat = 0;
  let ticksArret = 0;
  const urlsEnEchec = new Set();

  const heure = () => new Date().toTimeString().slice(0, 8);
  const hote = (url) => new URL(url).hostname;
  const copie = () => JSON.parse(JSON.stringify(mission));
  const attendre = () => new Promise((resoudre) => setTimeout(resoudre, 120));

  function journaliser(type, message) {
    mission.journal.push({ ts: heure(), type, message, budget_restant: mission.budget.restant });
  }

  function consommer() {
    mission.budget.restant = Math.max(0, mission.budget.restant - 1);
  }

  function terminerSiLimiteAtteinte() {
    if (mission.budget.restant <= 0) {
      mission.statut = "budget_exhausted";
      journaliser("etat", "BUDGET_EXHAUSTED plus aucune tentative disponible");
      return true;
    }
    if (mission.temps.ecoule_s >= mission.temps.max_s) {
      mission.statut = "deadline_reached";
      journaliser("etat", `DEADLINE_REACHED échéance de ${mission.temps.max_s / 60} min atteinte`);
      return true;
    }
    return false;
  }

  function etape() {
    if (phase === "recherche") {
      consommer();
      journaliser("recherche", `SEARCH "${mission.sujet}" k=5 → 5 résultats`);
      phase = "ouvrir";
      return;
    }
    if (phase === "ouvrir") {
      const domaine = mission.domaines[compteur % mission.domaines.length];
      const url = `https://${domaine}${CHEMINS[compteur % CHEMINS.length]}`;
      compteur += 1;
      if (compteur % 4 === 3) urlsEnEchec.add(url);
      source = { url, statut: "en_cours", tentatives: 1 };
      mission.sources.push(source);
      consommer();
      journaliser("lecture", `FETCH ${url} → en cours`);
      phase = "resoudre";
      return;
    }
    if (phase === "resoudre") {
      if (urlsEnEchec.has(source.url)) {
        if (source.tentatives === 1) {
          source.tentatives = 2;
          consommer();
          journaliser("erreur", `FETCH ${source.url} → timeout (1/2), nouvelle tentative`);
          return;
        }
        source.statut = "abandon";
        journaliser("abandon", `ABANDON ${hote(source.url)} : 2 tentatives atteintes`);
      } else {
        source.statut = "ok";
        okDepuisConstat += 1;
        journaliser("lecture", `FETCH ${source.url} → ok (200), 1 page conservée`);
      }
      phase = okDepuisConstat >= 2 ? "constat" : compteur % 3 === 0 ? "recherche" : "ouvrir";
      return;
    }
    if (phase === "constat") {
      const preuves = mission.sources.filter((s) => s.statut === "ok").slice(-2).map((s) => s.url);
      const n = mission.constats.length;
      mission.constats.push({
        id: `c${n + 1}`,
        titre: TITRES[n % TITRES.length],
        resume: RESUMES[n % RESUMES.length],
        interet_developpeur: IMPACTS[n % IMPACTS.length],
        sources: preuves,
        confiance: preuves.length > 1 ? "corroborated" : "single_source",
        date_evenement: new Date(Date.now() - (n + 1) * 86400000).toISOString().slice(0, 10),
        statut_date: "in_window",
      });
      consommer();
      journaliser("constat", `SAVE constat #${n + 1}, ${preuves.length} preuve(s)`);
      okDepuisConstat = 0;
      phase = "ouvrir";
    }
  }

  function avancer() {
    if (!mission) return;
    if (mission.statut === "pending") {
      mission.statut = "running";
      journaliser("etat", `START sujet="${mission.sujet}" budget=${mission.budget.max} échéance=${mission.temps.max_s / 60}min`);
      return;
    }
    if (mission.statut === "stopping") {
      ticksArret += 1;
      if (ticksArret >= 2) {
        mission.statut = "stopped";
        journaliser("etat", `STOPPED budget restant=${mission.budget.restant}, écoulé=${Math.round(mission.temps.ecoule_s)}s`);
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
    async creerMission(payload) {
      await attendre();
      mission = {
        id: `demo-${Date.now().toString(36)}`,
        statut: "pending",
        sujet: payload.sujet,
        domaines: payload.domaines,
        budget: { restant: payload.budget_max, max: payload.budget_max },
        temps: { ecoule_s: 0, max_s: payload.duree_max_minutes * 60 },
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
        journaliser("etat", "STOPPING arrêt demandé, appel en cours borné par son délai");
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
  presets: Array.from(document.querySelectorAll(".preset")),
  resumeMission: $("resume-mission"),
  erreurFormulaire: $("erreur-formulaire"),
  boutonLancer: $("bouton-lancer"),

  bandeauDemo: $("bandeau-demo"),
  bandeauConnexion: $("bandeau-connexion"),
  bandeauErreur: $("bandeau-erreur"),
  etatBadgeGrand: $("etat-badge-grand"),
  etatDescription: $("etat-description"),
  derniereAction: $("derniere-action"),
  statSourcesOk: $("stat-sources-ok"),
  statSourcesAbandon: $("stat-sources-abandon"),
  statConstats: $("stat-constats"),
  boutonArret: $("bouton-arret"),
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

  iconeChargementLancer: $("bouton-lancer").querySelector(".icone-chargement"),
  texteBoutonLancer: $("bouton-lancer").querySelector(".bouton-texte"),
  iconeArret: $("bouton-arret").querySelector("use"),
  texteArret: $("bouton-arret").querySelector(".bouton-texte"),
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
  return /^https?:\/\//i.test(url);
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
    .replace(/:\d+$/, "");
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
  else if (!MOTIF_DOMAINE.test(domaine)) erreur = "Un domaine ressemble à exemple.org, sans http:// ni chemin.";
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
  };
}

function validerFormulaire() {
  const valeurs = lireFormulaire();
  const erreurs = [];

  if (!valeurs.sujet) erreurs.push("Le sujet est obligatoire.");
  if (valeurs.domaines.length === 0) erreurs.push("Ajoutez au moins un domaine autorisé.");
  if (!Number.isInteger(valeurs.budget) || valeurs.budget < 1) erreurs.push("Le budget d'actions doit être un entier positif.");
  if (!Number.isInteger(valeurs.duree) || valeurs.duree < 1) erreurs.push("La durée maximale doit être un entier positif, en minutes.");

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
  majCurseurBudget();
  majCurseurDuree();
  mettreAJourFormulaire();
}

els.champSujet.addEventListener("input", mettreAJourFormulaire);

els.formLancement.addEventListener("submit", async (evenement) => {
  evenement.preventDefault();
  if (els.champDomaine.value.trim()) ajouterDomaine(els.champDomaine.value);

  const valeurs = validerFormulaire();
  if (!valeurs.valide) {
    els.erreurFormulaire.textContent = valeurs.erreurs[0];
    els.erreurFormulaire.hidden = false;
    return;
  }

  definirChargement(true);
  try {
    const mission = await api.creerMission({
      sujet: valeurs.sujet,
      domaines: valeurs.domaines,
      budget_max: valeurs.budget,
      duree_max_minutes: valeurs.duree,
    });
    demarrerSuiviMission(mission);
  } catch {
    els.erreurFormulaire.textContent =
      "Impossible de lancer la recherche pour l'instant. Le service est peut-être indisponible.";
    els.erreurFormulaire.hidden = false;
    afficherToast("Le service ne répond pas.", "danger");
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
let intervalleId = null;
let horlogeId = null;

function definirAnneau(cercle, ratio) {
  const r = Math.min(1, Math.max(0, ratio));
  cercle.style.strokeDashoffset = `${CIRCONFERENCE_ANNEAU * (1 - r)}`;
}

// Synchronise une liste DOM append-only avec un tableau de données : seules
// les entrées nouvelles sont créées (et animées), les autres sont mises à
// jour en place. Indispensable avec un rafraîchissement toutes les secondes,
// sinon le journal clignote et le défilement saute.
function synchroniserListe(conteneur, items, cleDe, creerNoeud, mettreAJourNoeud) {
  const existants = new Map();
  for (const enfant of conteneur.children) existants.set(enfant.dataset.cle, enfant);

  items.forEach((item, index) => {
    const cle = String(cleDe(item, index));
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
}

// Sources

const ICONES_STATUT_SOURCE = { ok: "ok", en_cours: "chargement", abandon: "croix" };

function libelleStatutSource(source) {
  if (source.statut === "ok") return "ok";
  if (source.statut === "en_cours") return source.tentatives > 1 ? `essai ${source.tentatives}` : "en cours";
  return "abandon";
}

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
  li.querySelector(".source-hote").textContent = hote;
  li.querySelector(".source-chemin").textContent = chemin;
  li.title = source.url;

  const ic = li.querySelector(".source-icone");
  const statut = li.querySelector(".source-statut");
  const empreinte = `${source.statut}|${source.tentatives ?? ""}`;
  if (statut.dataset.empreinte !== empreinte) {
    statut.dataset.empreinte = empreinte;
    statut.dataset.statut = source.statut;
    ic.dataset.statut = source.statut;
    statut.textContent = libelleStatutSource(source);
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

  const pied = document.createElement("div");
  pied.className = "constat-pied";
  for (const url of constat.sources || []) {
    const { hote, chemin } = hoteEtChemin(url);
    let lien;
    if (urlSure(url)) {
      lien = document.createElement("a");
      lien.href = url;
      lien.target = "_blank";
      lien.rel = "noopener noreferrer";
    } else {
      lien = document.createElement("span");
    }
    lien.className = "constat-source";
    lien.title = url;
    lien.appendChild(icone("lien"));
    const libelle = document.createElement("span");
    libelle.textContent = hote + chemin;
    lien.appendChild(libelle);
    pied.appendChild(lien);
  }
  const date = libelleDateConstat(constat);
  if (date) {
    const el = document.createElement("span");
    el.className = "constat-date";
    el.textContent = date;
    pied.appendChild(el);
  }
  li.appendChild(pied);

  return li;
}

// Journal

function typeEntreeJournal(entree) {
  if (entree.type) return entree.type;
  const message = String(entree.message || "").trim().toUpperCase();
  if (message.startsWith("SEARCH")) return "recherche";
  if (message.startsWith("FETCH") || message.startsWith("READ")) return "lecture";
  if (message.startsWith("ABANDON")) return "abandon";
  if (message.startsWith("SAVE")) return "constat";
  if (/^(START|STOP|COMPLETED|BUDGET|DEADLINE|FAILED|ETAT|STATE)/.test(message)) return "etat";
  if (/ERREUR|ERROR|TIMEOUT|ECHEC|ÉCHEC/.test(message)) return "erreur";
  return "info";
}

function creerNoeudJournal(entree) {
  const li = document.createElement("li");
  li.dataset.type = typeEntreeJournal(entree);

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
    budget.textContent = `budget ${entree.budget_restant}`;
  }

  li.append(point, heure, message, budget);
  return li;
}

function ligneJournal(entree) {
  const budget = entree.budget_restant !== undefined && entree.budget_restant !== null ? `  [budget ${entree.budget_restant}]` : "";
  return `${entree.ts}  ${entree.message}${budget}`;
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

  const sources = mission.sources || [];
  synchroniserListe(els.listeSources, sources, (s) => s.url, creerNoeudSource, mettreAJourNoeudSource);
  els.sourcesVide.hidden = sources.length !== 0;
  els.sourcesCompteur.textContent = String(sources.length);
  const nbOk = sources.filter((s) => s.statut === "ok").length;
  const nbAbandon = sources.filter((s) => s.statut === "abandon").length;
  definirTexteAvecEclat(els.statSourcesOk, String(nbOk));
  definirTexteAvecEclat(els.statSourcesAbandon, String(nbAbandon));

  const constats = mission.constats || [];
  synchroniserListe(els.listeConstats, constats, (c, i) => c.id ?? i, creerNoeudConstat, () => {});
  els.syntheseVide.hidden = constats.length !== 0;
  els.syntheseVideTexte.textContent = ETATS_TERMINAUX.has(statut)
    ? "Aucune nouveauté pertinente trouvée. C'est un résultat valide, pas une panne."
    : "Aucun constat pour l'instant.";
  definirTexteAvecEclat(els.statConstats, String(constats.length));
  const partielle = (statut !== "completed" && statut !== "pending") || nbAbandon > 0;
  els.synthesePartielle.hidden = !partielle;

  const journal = mission.journal || [];
  synchroniserListe(els.journalListe, journal, (_e, i) => i, creerNoeudJournal, () => {});
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
  demarrerRafraichissement();
  demarrerHorloge();
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
  if (!missionCourante) return;
  try {
    const mission = await api.obtenirMission(missionCourante.id);
    if (!missionCourante) return;
    missionCourante = mission;
    derniereReception = Date.now();
    echecsConsecutifs = 0;
    els.bandeauConnexion.hidden = true;
    rendreMission(mission);
  } catch {
    echecsConsecutifs += 1;
    if (echecsConsecutifs >= 2) els.bandeauConnexion.hidden = false;
  }
}

// ---------- Actions du tableau de bord ----------

els.boutonArret.addEventListener("click", async () => {
  if (!missionCourante) return;
  rendreBoutonArret(missionCourante.statut, true);
  try {
    const mission = await api.arreterMission(missionCourante.id);
    if (!missionCourante) return;
    missionCourante = mission;
    derniereReception = Date.now();
    rendreMission(mission);
  } catch {
    rendreBoutonArret(missionCourante.statut);
    afficherToast("L'ordre d'arrêt n'a pas pu être transmis. Réessayez.", "danger");
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
  const lignes = (missionCourante?.journal || []).map(ligneJournal);
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

mettreAJourFormulaire();
if (MODE_DEMO) afficherToast("Mode démonstration : données simulées, aucun appel réseau.", "attention");
