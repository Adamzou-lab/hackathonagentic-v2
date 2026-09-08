/* Transport de démonstration explicite. Aucun appel réseau. */
window.createLockinDemo = function () {
  let state,
    step = 0,
    scenario,
    serial = 0;
  const missions = new Map(),
    watches = new Map();
  const normalize = (value) => value.trim().toLowerCase().replace(/\s+/g, " ");
  const clone = (value) => structuredClone(value);
  const summary = (watch) => {
    const last = missions.get(watch.latest_mission_id);
    return {
      ...watch,
      status: last.status,
      findings_count: watch.findings.length,
      run_count: watch.runs.length,
      findings: undefined,
      runs: undefined,
    };
  };
  const syncWatch = () => {
    const watch = watches.get(state.watch_id);
    watch.updated_at = new Date().toISOString();
    watch.domains = [...state.domains];
    watch.auto_sources = state.auto_sources;
    const run = {
      id: state.id,
      created_at: state.created_at,
      ended_at: state.ended_at,
      status: state.status,
      actions_used: state.actions_used,
      findings_count: state.findings.length,
      new_findings_count: state.new_findings_count,
      updated_findings_count: state.updated_findings_count,
    };
    const index = watch.runs.findIndex((r) => r.id === state.id);
    if (index < 0) watch.runs.push(run);
    else watch.runs[index] = run;
  };
  const emit = (kind, data) =>
    state.events.push({
      seq: state.events.length + 1,
      at: new Date().toISOString(),
      kind,
      data,
    });
  const finish = (status) => {
    state.status = status;
    state.current_action = null;
    state.ended_at = new Date().toISOString();
    state.summary.partial = status !== "completed";
    emit("finished", { status, error: state.error });
    syncWatch();
  };
  return async function (path, options = {}) {
    if (path === "config") return { provider_ready: true };
    if (path.startsWith("watches?") || path === "watches") {
      const parameters = Object.fromEntries(
        (path.split("?")[1] || "").split("&").map((part) => {
          const pair = part.split("=");
          return [
            pair[0],
            decodeURIComponent((pair[1] || "").replace(/\+/g, " ")),
          ];
        }),
      );
      const query = normalize(parameters.query || "");
      const offset = Number(parameters.offset || 0),
        limit = Number(parameters.limit || 50);
      const list = [...watches.values()]
        .filter((w) => normalize(w.subject).includes(query))
        .map(summary);
      return clone({
        watches: list.slice(offset, offset + limit),
        total: list.length,
      });
    }
    if (path.startsWith("watches/")) {
      const watch = watches.get(decodeURIComponent(path.split("/")[1]));
      if (!watch) throw new Error("Veille de démonstration introuvable.");
      return clone(watch);
    }
    if (path === "missions" && options.method === "POST") {
      const r = JSON.parse(options.body);
      const automatic = Boolean(r.auto_sources);
      const equivalent = (w) =>
        normalize(w.subject) === normalize(r.subject) &&
        w.auto_sources === automatic &&
        (automatic ||
          JSON.stringify([...w.domains].sort()) ===
            JSON.stringify([...r.domains].sort()));
      let watch = r.watch_id
        ? watches.get(r.watch_id)
        : [...watches.values()].find(equivalent);
      if (r.watch_id && !watch)
        throw new Error("Veille de démonstration introuvable.");
      scenario = document.getElementById("lk-scenario").value;
      // Scénario choisi explicitement : il illustre la confirmation sans classifier la demande.
      if (!watch && !r.allow_new && scenario === "similar" && watches.size) {
        const error = new Error("Une veille proche existe déjà.");
        error.status = 409;
        error.detail = {
          code: "similar_watches",
          candidates: [summary([...watches.values()][0])],
        };
        throw error;
      }
      if (watch) {
        const prior = missions.get(watch.latest_mission_id);
        if (
          prior.status === "running" ||
          (!r.force_refresh &&
            prior.status === "completed" &&
            prior.action_budget === r.action_budget &&
            prior.duration_seconds === r.duration_minutes * 60)
        )
          return {
            ...clone(prior),
            reuse: {
              reason:
                prior.status === "running"
                  ? "already_running"
                  : "recent_completed",
            },
          };
      }
      step = 0;
      const now = new Date().toISOString();
      const id = "demo-" + ++serial;
      if (!watch) {
        watch = {
          id: "watch-" + id,
          subject: r.subject,
          created_at: now,
          updated_at: now,
          domains: [],
          auto_sources: automatic,
          latest_mission_id: id,
          findings: [],
          runs: [],
        };
        watches.set(watch.id, watch);
      }
      watch.latest_mission_id = id;
      state = {
        ...r,
        auto_sources: automatic,
        domains: automatic
          ? ["example.com", "example.org", "example.net"]
          : [...r.domains],
        id,
        watch_id: watch.id,
        status: "running",
        created_at: now,
        elapsed_seconds: 0,
        duration_seconds: r.duration_minutes * 60,
        actions_used: 0,
        actions_remaining: r.action_budget,
        model_calls_used: 0,
        network_requests_used: 0,
        current_action: null,
        error: null,
        findings: [],
        sources: [],
        events: [],
        new_findings_count: 0,
        updated_findings_count: 0,
        summary: { partial: true, text: "" },
      };
      missions.set(id, state);
      emit("created", { request: r });
      emit("started", {});
      if (automatic) {
        const selected = [...state.domains];
        state.domains = [];
        for (const tool of ["discover_sources", "select_sources"]) {
          if (state.actions_used >= state.action_budget) {
            finish("budget_exhausted");
            return clone(state);
          }
          state.actions_used++;
          state.actions_remaining = state.action_budget - state.actions_used;
          emit("action_started", {
            tool,
            action_number: state.actions_used,
            parameters:
              tool === "discover_sources"
                ? { query: state.subject }
                : { domains: selected },
          });
          emit("action_finished", {
            tool,
            action_number: state.actions_used,
            result: { domains: selected, simulated: true },
          });
        }
        state.domains = selected;
        emit("sources_selected", {
          domains: selected,
          reason:
            "Domaines fictifs réservés aux exemples. Aucun choix réel du modèle.",
        });
      }
      if (watch.runs.length)
        emit("enrichment_prepared", {
          reason: "Actualisation fictive : résultats connus conservés.",
          known_findings: watch.findings.length,
        });
      syncWatch();
      return clone(state);
    }
    const requestedId = decodeURIComponent(path.split("/")[1] || "");
    // L’alias demo reste réservé aux tests historiques du transport.
    const requested =
      requestedId === "demo" ? state : missions.get(requestedId);
    if (!requested) throw new Error("Mission de démonstration introuvable.");
    if (requested !== state) return clone(requested);
    if (path.endsWith("/stop")) {
      emit("stop_requested", {});
      if (state.current_action)
        emit("action_finished", {
          tool: state.current_action,
          action_number: state.actions_used,
          result: { error: "cancelled" },
        });
      finish("stopped");
      return clone(state);
    }
    if (state.status !== "running") return clone(state);
    state.elapsed_seconds = Math.floor(
      (Date.now() - new Date(state.created_at)) / 1000,
    );
    if (state.elapsed_seconds >= state.duration_seconds) {
      finish("deadline_reached");
      return structuredClone(state);
    }
    const url = "https://" + state.domains[0] + "/";
    if (step % 2 === 0) {
      if (state.actions_used >= state.action_budget) {
        finish("budget_exhausted");
        return structuredClone(state);
      }
      state.actions_used++;
      state.actions_remaining = state.action_budget - state.actions_used;
      state.current_action =
        step === 0 ? "search_web" : step === 2 ? "read_page" : "save_finding";
      emit("action_started", {
        tool: state.current_action,
        action_number: state.actions_used,
        parameters:
          step === 0
            ? { query: state.subject, k: 3 }
            : step === 2
              ? { url }
              : {
                  finding: { title: "Exemple de constat — données fictives" },
                  idempotency_key: "demo-finding",
                },
      });
    } else {
      const failure =
        scenario === "disabled" && step === 1
          ? "tool_disabled_for_test"
          : scenario === "error" && step === 3
            ? "unavailable"
            : null;
      let result;
      if (failure) {
        result = { error: failure };
        emit("tool_error", { tool: state.current_action, code: failure });
      } else if (step === 1)
        result = [{ url, title: "Source de démonstration — non consultée" }];
      else if (step === 3) {
        result = {
          source_id: "demo-source",
          url,
          title: "Exemple fictif",
          status: "ok",
          retrieved_at: new Date().toISOString(),
        };
        state.sources.push(result);
      } else {
        const watch = watches.get(state.watch_id);
        const additional = watch.runs.length > 1;
        const findingId = additional ? "demo-addition" : "demo-finding";
        const finding = {
          finding_id: findingId,
          title: additional
            ? "Nouveau constat — actualisation fictive"
            : "Exemple de constat — données fictives",
          summary:
            "Ce résultat illustre la présentation. Il ne provient pas d’une recherche réelle.",
          developer_impact:
            "Vérifier la lisibilité des résultats et de leur provenance.",
          date_status: "unknown",
          event_date: null,
          evidence: [
            {
              source_id: "demo-source",
              quote:
                "Extrait fictif utilisé uniquement pour cette démonstration.",
            },
          ],
          caveats: ["Mode démo : aucune source réellement consultée."],
        };
        state.findings.push(finding);
        const exists = watch.findings.some((f) => f.finding_id === findingId);
        result = {
          finding_id: findingId,
          disposition: exists ? "duplicate" : "created",
        };
        if (!exists) {
          state.new_findings_count++;
          watch.findings.push({
            ...clone(finding),
            mission_id: state.id,
            source_links: [{ url, title: "Source fictive" }],
            change: "new",
          });
        }
      }
      emit("action_finished", {
        tool: state.current_action,
        action_number: state.actions_used,
        result,
      });
      state.current_action = null;
      if (failure) {
        state.error = failure;
        finish("failed");
      } else if (step === 5) finish("completed");
    }
    step++;
    syncWatch();
    return structuredClone(state);
  };
};
