(function (root) {
  "use strict";
  const number = value => Number.isSafeInteger(value) && value >= 0
    ? value.toLocaleString("fr-FR") : "Indisponible";
  function presentation(state, demo = false) {
    const u = state.usage;
    const reuse = state.reuse?.reason;
    const parts = [];
    if (demo) parts.push("Démonstration simulée · aucune consommation API réelle.");
    if (reuse === "recent_completed") parts.push("Veille réutilisée : aucun nouvel appel IA. Bilan de la mission d’origine.");
    else if (reuse === "already_running") parts.push("Mission déjà en cours : aucun second lancement. Sa consommation continue d’évoluer.");
    if (!u) parts.push("Mesures de tokens indisponibles pour cette mission.");
    else if (!u.tokens_complete) parts.push("Consommation incomplète : un appel est en cours ou sa mesure n’a pas été reçue.");
    else parts.push("Tokens mesurés, cache inclus. Les appels comptent les tentatives, même en échec.");
    const observed = u?.observed_tokens;
    if (observed) parts.push(`Détail reçu : ${number(observed.input_tokens)} en entrée · ${number(observed.output_tokens)} en sortie · ${number(observed.cache_read_input_tokens)} lus en cache · ${number(observed.cache_creation_input_tokens)} écrits en cache.`);
    return {
      tokens: u?.tokens_complete ? number(u.total_tokens) : "Indisponible",
      calls: number(u?.model_calls ?? state.model_calls_used),
      duration: number(u?.elapsed_seconds ?? state.elapsed_seconds),
      note: parts.join(" "),
    };
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { presentation };
  else root.LockinUsage = { presentation };
})(typeof window !== "undefined" ? window : globalThis);
