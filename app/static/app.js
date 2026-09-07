"use strict";

// Contrat réel : voir API.md. Jeton conservé uniquement dans la mémoire de la page.
let jetonMemoire = "";
function adapterMission(m) {
  const sources = m.sources || [];
  const parId = new Map(sources.filter(s => s.source_id).map(s => [s.source_id, s.url]));
  return {
    id:m.id, statut:m.status, sujet:m.subject,
    budget:{restant:m.actions_remaining,max:m.action_budget},
    temps:{ecoule_s:m.elapsed_seconds,max_s:m.duration_seconds},
    sources:sources.map(s=>({...s,statut:s.status === "ok" ? "ok" : "abandon"})),
    constats:(m.findings||[]).map(f=>({id:f.finding_id,titre:f.title,resume:f.summary,
      impact:f.developer_impact,date:f.event_date || "Date inconnue",
      sources:(f.evidence||[]).map(e=>parId.get(e.source_id)||e.source_id)})),
    journal:(m.events||[]).map(e=>({ts:e.at,message:e.kind+" — "+JSON.stringify(e.data)})),
    erreur:m.error ? {message:m.error}:null, partielle:m.summary?.partial ?? true
  };
}
async function requete(path, method="GET", body) {
  const headers = {"Authorization":"Bearer "+jetonMemoire};
  if(body) headers["Content-Type"]="application/json";
  const r = await fetch(path,{method,headers,body:body ? JSON.stringify(body):undefined});
  const data = await r.json();
  if(!r.ok) {
    const messages={401:"Jeton opérateur incorrect.",403:"Accès refusé.",409:"Une mission est déjà en cours.",503:"Configuration serveur incomplète. Vérifiez la clé Anthropic et le jeton opérateur."};
    throw new Error(messages[r.status] || (typeof data.detail === "string" ? data.detail : "Paramètres invalides. Vérifiez le sujet, les domaines et les limites."));
  }
  return adapterMission(data);
}
const api = {
  creerMission(p) { return requete("/api/missions","POST",{subject:p.sujet,domains:p.domaines,action_budget:p.budget_max,duration_minutes:p.duree_max_minutes}); },
  obtenirMission(id) { return requete("/api/missions/"+encodeURIComponent(id)); },
  arreterMission(id) { return requete("/api/missions/"+encodeURIComponent(id)+"/stop","POST"); }
};

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

const ETATS_TERMINAUX = new Set([
  "stopped",
  "completed",
  "budget_exhausted",
  "deadline_reached",
  "failed",
]);

const INTERVALLE_RAFRAICHISSEMENT_MS = 1000;

const els = {
  ecranAccueil: document.getElementById("ecran-accueil"),
  ecranRecherche: document.getElementById("ecran-recherche"),
  formLancement: document.getElementById("form-lancement"),
  champSujet: document.getElementById("champ-sujet"),
  nombreDomaines: document.getElementById("nombre-domaines"),
  domainesConteneur: document.getElementById("domaines-conteneur"),
  champBudget: document.getElementById("champ-budget"),
  champDuree: document.getElementById("champ-duree"),
  boutonLancer: document.getElementById("bouton-lancer"),
  erreurFormulaire: document.getElementById("erreur-formulaire"),

  sujetValeur: document.getElementById("sujet-valeur"),
  etatBadge: document.getElementById("etat-badge"),
  barreActivite: document.getElementById("barre-activite"),
  anneauBudgetBloc: document.getElementById("anneau-budget-bloc"),
  anneauBudgetCercle: document.getElementById("anneau-budget-cercle"),
  anneauBudgetValeur: document.getElementById("anneau-budget-valeur"),
  anneauTempsBloc: document.getElementById("anneau-temps-bloc"),
  anneauTempsCercle: document.getElementById("anneau-temps-cercle"),
  anneauTempsValeur: document.getElementById("anneau-temps-valeur"),
  bandeauConnexion: document.getElementById("bandeau-connexion"),
  bandeauErreur: document.getElementById("bandeau-erreur"),
  boutonArret: document.getElementById("bouton-arret"),
  listeSources: document.getElementById("liste-sources"),
  synthesePartielle: document.getElementById("synthese-partielle"),
  syntheseVide: document.getElementById("synthese-vide"),
  listeConstats: document.getElementById("liste-constats"),
  journalCompteur: document.getElementById("journal-compteur"),
  journalListe: document.getElementById("journal-liste"),
  boutonNouvelleRecherche: document.getElementById("bouton-nouvelle-recherche"),
};

const CIRCONFERENCE_ANNEAU = 2 * Math.PI * 52;
[els.anneauBudgetCercle, els.anneauTempsCercle].forEach((cercle) => {
  cercle.style.strokeDasharray = `${CIRCONFERENCE_ANNEAU}`;
});

let intervalleId = null;
let missionCourante = null;
let echecsConsecutifs = 0;
let lancementEnCours = false;
let lectureEnCours = false;

// ---------- Effet de clic (ondulation) ----------

function declencherOndulation(bouton, evenement) {
  const precedente = bouton.querySelector(".ondulation");
  if (precedente) precedente.remove();

  const rect = bouton.getBoundingClientRect();
  const taille = Math.max(rect.width, rect.height) * 1.6;
  const x = (evenement.clientX ?? rect.left + rect.width / 2) - rect.left;
  const y = (evenement.clientY ?? rect.top + rect.height / 2) - rect.top;

  const onde = document.createElement("span");
  onde.className = "ondulation";
  onde.style.width = `${taille}px`;
  onde.style.height = `${taille}px`;
  onde.style.left = `${x - taille / 2}px`;
  onde.style.top = `${y - taille / 2}px`;

  bouton.appendChild(onde);
  onde.addEventListener("animationend", () => onde.remove(), { once: true });
}

document.querySelectorAll(".bouton").forEach((bouton) => {
  bouton.addEventListener("pointerdown", (evenement) => {
    if (bouton.disabled) return;
    declencherOndulation(bouton, evenement);
  });
});

// ---------- Formulaire de lancement ----------

function regenererChampsDomaines() {
  const n = Number(els.nombreDomaines.value);
  const valeursActuelles = Array.from(
    els.domainesConteneur.querySelectorAll("input")
  ).map((input) => input.value);

  els.domainesConteneur.innerHTML = "";
  for (let i = 0; i < n; i += 1) {
    const bloc = document.createElement("div");
    bloc.className = "champ domaine-champ";

    const label = document.createElement("label");
    label.setAttribute("for", `champ-domaine-${i}`);
    label.textContent = `Domaine autorisé ${i + 1}`;

    const input = document.createElement("input");
    input.type = "text";
    input.id = `champ-domaine-${i}`;
    input.name = `domaine-${i}`;
    input.placeholder = "exemple.org";
    input.autocomplete = "off";
    input.required = true;
    input.value = valeursActuelles[i] || "";

    bloc.appendChild(label);
    bloc.appendChild(input);
    els.domainesConteneur.appendChild(bloc);
  }

  validerFormulaire();
}

const MOTIF_DOMAINE = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/i;

function listeDomaines() {
  return Array.from(els.domainesConteneur.querySelectorAll("input")).map((i) =>
    i.value.trim()
  );
}

function validerFormulaire() {
  const sujet = els.champSujet.value.trim();
  const domaines = listeDomaines();
  const budget = Number(els.champBudget.value);
  const duree = Number(els.champDuree.value);

  const erreurs = [];

  if (!sujet || sujet.length > 500) erreurs.push("Le sujet doit contenir entre 1 et 500 caractères.");
  if (document.getElementById("jeton-operateur").value.trim().length < 32) erreurs.push("Jeton opérateur requis.");

  if (domaines.some((d) => !d)) {
    erreurs.push("Chaque domaine autorisé doit être renseigné.");
  } else if (domaines.some((d) => !MOTIF_DOMAINE.test(d))) {
    erreurs.push("Un domaine doit ressembler à exemple.org, sans http:// ni chemin.");
  } else if (new Set(domaines.map((d) => d.toLowerCase())).size !== domaines.length) {
    erreurs.push("Les domaines autorisés doivent être différents les uns des autres.");
  }

  if (!Number.isInteger(budget) || budget < 1 || budget > 100) {
    erreurs.push("Le budget d'actions doit être un entier positif.");
  }

  if (!Number.isInteger(duree) || duree < 1 || duree > 30) {
    erreurs.push("La durée maximale doit être un entier positif, en minutes.");
  }

  const valide = erreurs.length === 0;
  els.boutonLancer.disabled = !valide || lancementEnCours;
  els.erreurFormulaire.hidden = true;

  return { valide, sujet, domaines, budget, duree };
}

els.formLancement.addEventListener("input", validerFormulaire);
els.nombreDomaines.addEventListener("change", regenererChampsDomaines);

els.formLancement.addEventListener("submit", async (evenement) => {
  evenement.preventDefault();
  const { valide, sujet, domaines, budget, duree } = validerFormulaire();
  if (!valide || lancementEnCours) return;
  lancementEnCours = true;
  jetonMemoire = document.getElementById("jeton-operateur").value.trim();
  els.boutonLancer.disabled = true;

  try {
    const mission = await api.creerMission({
      sujet,
      domaines,
      budget_max: budget,
      duree_max_minutes: duree,
    });
    demarrerSuiviMission(mission);
  } catch (erreur) {
    els.erreurFormulaire.textContent =
      erreur.message;
    els.erreurFormulaire.hidden = false;
    els.boutonLancer.disabled = false;
  } finally { lancementEnCours = false; }
});

// ---------- Écran de recherche ----------

function afficherEcranRecherche(sujet) {
  els.ecranAccueil.hidden = true;
  els.ecranRecherche.hidden = false;
  els.sujetValeur.textContent = sujet;
}

function afficherEcranAccueil() {
  els.ecranRecherche.hidden = true;
  els.ecranAccueil.hidden = false;
  els.formLancement.reset();
  document.getElementById("jeton-operateur").value = jetonMemoire;
  regenererChampsDomaines();
  els.boutonLancer.disabled = true;
}

function formaterTemps(secondes) {
  const s = Math.max(0, Math.round(secondes));
  const min = Math.floor(s / 60);
  const rest = s % 60;
  return `${min}:${String(rest).padStart(2, "0")}`;
}

function definirAnneau(cercle, ratio) {
  const r = Math.min(1, Math.max(0, ratio));
  cercle.style.strokeDashoffset = `${CIRCONFERENCE_ANNEAU * (1 - r)}`;
}

function definirTexteAvecEclat(el, texte) {
  if (el.textContent === texte) return;
  el.textContent = texte;
  el.classList.remove("valeur-maj");
  void el.offsetWidth; // relance l'animation même si la classe était déjà posée
  el.classList.add("valeur-maj");
}

// Synchronise une liste DOM append-only avec un tableau de données, sans
// tout reconstruire à chaque appel : seules les entrées nouvelles sont
// créées (et animées), les entrées déjà affichées sont mises à jour en
// place. Nécessaire pour que le journal, les sources et les constats
// restent lisibles pendant un rafraîchissement toutes les secondes.
function synchroniserListe(conteneur, items, cleDe, creerNoeud, mettreAJourNoeud) {
  const existants = new Map();
  for (const enfant of Array.from(conteneur.children)) {
    existants.set(enfant.dataset.cle, enfant);
  }
  const nouvellesCles = new Set(items.map((item,index)=>String(cleDe(item,index))));
  for (const [cle,noeud] of existants) if (!nouvellesCles.has(cle)) noeud.remove();
  items.forEach((item, index) => {
    const cle = String(cleDe(item, index));
    const noeudExistant = existants.get(cle);
    if (noeudExistant) {
      mettreAJourNoeud(noeudExistant, item);
    } else {
      const noeud = creerNoeud(item);
      noeud.dataset.cle = cle;
      noeud.classList.add("entree-nouvelle");
      conteneur.appendChild(noeud);
    }
  });
}

function libelleStatutSource(statut) {
  return statut === "ok" ? "ok" : statut === "en_cours" ? "en cours" : "abandon";
}

function creerNoeudSource(source) {
  const li = document.createElement("li");
  const url = document.createElement("span");
  url.className = "source-url";
  const statut = document.createElement("span");
  statut.className = "source-statut";
  li.appendChild(url);
  li.appendChild(statut);
  mettreAJourNoeudSource(li, source);
  return li;
}

function mettreAJourNoeudSource(li, source) {
  const url = li.querySelector(".source-url");
  const statut = li.querySelector(".source-statut");
  url.textContent = source.url;
  url.title = source.url;
  if (statut.dataset.statut !== source.statut) {
    statut.dataset.statut = source.statut;
    statut.textContent = libelleStatutSource(source.statut);
    statut.classList.remove("statut-maj");
    void statut.offsetWidth;
    statut.classList.add("statut-maj");
  }
}

function creerNoeudConstat(constat) {
  const li = document.createElement("li");

  const titre = document.createElement("p");
  titre.className = "constat-titre";
  titre.textContent = constat.titre;

  const resume = document.createElement("p");
  resume.textContent = constat.resume + "\nIntérêt pratique : " + (constat.impact || "") + "\n" + constat.date;

  const sourcesConstat = document.createElement("p");
  sourcesConstat.className = "constat-sources";
  sourcesConstat.textContent = `Sources : ${(constat.sources || []).join(", ")}`;

  li.appendChild(titre);
  li.appendChild(resume);
  li.appendChild(sourcesConstat);
  return li;
}

function creerNoeudJournal(entree) {
  const li = document.createElement("li");
  li.textContent = `${entree.ts}  ${entree.message}`;
  return li;
}

function rendreMission(mission) {
  const libelle = LIBELLES_ETAT[mission.statut] || mission.statut;
  els.etatBadge.textContent = libelle;
  els.etatBadge.dataset.etat = mission.statut;

  const missionActive =
    mission.statut === "pending" || mission.statut === "running" || mission.statut === "stopping";
  els.barreActivite.classList.toggle("barre-activite-active", missionActive);
  els.anneauBudgetBloc.classList.toggle("anneau-actif", missionActive);
  els.anneauTempsBloc.classList.toggle("anneau-actif", missionActive);

  const budget = mission.budget || { restant: 0, max: 0 };
  const budgetUtilise = budget.max - budget.restant;
  definirTexteAvecEclat(els.anneauBudgetValeur, `${budgetUtilise} / ${budget.max}`);
  definirAnneau(els.anneauBudgetCercle, budget.max ? budgetUtilise / budget.max : 0);

  const temps = mission.temps || { ecoule_s: 0, max_s: 0 };
  definirTexteAvecEclat(
    els.anneauTempsValeur,
    `${formaterTemps(temps.ecoule_s)} / ${formaterTemps(temps.max_s)}`
  );
  definirAnneau(els.anneauTempsCercle, temps.max_s ? temps.ecoule_s / temps.max_s : 0);

  const sources = mission.sources || [];
  synchroniserListe(
    els.listeSources,
    sources,
    (source) => source.url,
    creerNoeudSource,
    mettreAJourNoeudSource
  );

  const constats = mission.constats || [];
  const sourcesAbandonnees = sources.some((s) => s.statut === "abandon");
  const statutsNonAboutis = new Set([
    "running",
    "stopping",
    "stopped",
    "budget_exhausted",
    "deadline_reached",
    "failed",
  ]);
  const partielle = mission.partielle;
  els.synthesePartielle.hidden = !partielle;

  els.syntheseVide.hidden = constats.length !== 0;
  synchroniserListe(
    els.listeConstats,
    constats,
    (constat, index) => constat.id ?? index,
    creerNoeudConstat,
    () => {}
  );

  const journal = mission.journal || [];
  els.journalCompteur.textContent = String(journal.length);
  synchroniserListe(els.journalListe, journal, (_entree, index) => index, creerNoeudJournal, () => {});
  els.journalListe.scrollTop = els.journalListe.scrollHeight;

  if (mission.statut === "failed" && mission.erreur) {
    els.bandeauErreur.textContent = `Erreur : ${mission.erreur.message}`;
    els.bandeauErreur.hidden = false;
  } else {
    els.bandeauErreur.hidden = true;
  }

  els.boutonNouvelleRecherche.disabled = !ETATS_TERMINAUX.has(mission.statut);
  const enCours = mission.statut === "running" || mission.statut === "pending";
  els.boutonArret.hidden = !enCours && mission.statut !== "stopping";
  els.boutonArret.disabled = mission.statut === "stopping";

  if (ETATS_TERMINAUX.has(mission.statut)) {
    arreterRafraichissement();
  }
}

function demarrerSuiviMission(mission) {
  missionCourante = mission;
  els.listeSources.innerHTML = "";
  els.listeConstats.innerHTML = "";
  els.journalListe.innerHTML = "";
  afficherEcranRecherche(mission.sujet);
  rendreMission(mission);
  if (!ETATS_TERMINAUX.has(mission.statut)) demarrerRafraichissement();
}

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
    if (missionCourante?.id !== identifiant) return;
    missionCourante = mission;
    echecsConsecutifs = 0;
    els.bandeauConnexion.hidden = true;
    rendreMission(mission);
  } catch (erreur) {
    echecsConsecutifs += 1;
    if (echecsConsecutifs >= 2) {
      els.bandeauConnexion.hidden = false;
    }
  } finally { lectureEnCours = false; }
}

els.boutonArret.addEventListener("click", async () => {
  if (!missionCourante) return;
  els.boutonArret.disabled = true;
  try {
    const mission = await api.arreterMission(missionCourante.id);
    missionCourante = mission;
    rendreMission(mission);
  } catch (erreur) {
    els.boutonArret.disabled = false;
    els.bandeauConnexion.hidden = false;
  }
});

els.boutonNouvelleRecherche.addEventListener("click", () => {
  if (missionCourante && !ETATS_TERMINAUX.has(missionCourante.statut)) return;
  arreterRafraichissement();
  missionCourante = null;
  afficherEcranAccueil();
});

// ---------- Initialisation ----------

regenererChampsDomaines();
