/* Transport de démonstration explicite. Aucun appel réseau. */
window.createLockinDemo = function () {
  let state,
    step = 0,
    scenario;
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
    state.summary.partial = status !== "completed" || scenario !== "success";
    emit("finished", { status, error: state.error });
  };
  return async function (path, options = {}) {
    if (path === "config") return { provider_ready: true };
    if (path === "missions" && options.method === "POST") {
      const r = JSON.parse(options.body);
      step = 0;
      scenario = document.getElementById("lk-scenario").value;
      state = {
        ...r,
        id: "demo-" + Date.now(),
        status: "running",
        created_at: new Date().toISOString(),
        elapsed_seconds: 0,
        duration_seconds: r.duration_minutes * 60,
        actions_used: 0,
        actions_remaining: r.action_budget,
        model_calls_used: 0,
        network_requests_used: 0,
        last_request_cost: null,
        total_estimated_cost_usd: 0,
        current_action: null,
        error: null,
        findings: [],
        sources: [],
        events: [],
        summary: { partial: true, text: "" },
      };
      emit("created", { request: r });
      emit("started", {});
      return structuredClone(state);
    }
    if (!state) throw new Error("Mission de démonstration introuvable.");
    if (path.endsWith("/stop")) {
      emit("stop_requested", {});
      if (state.current_action)
        emit("action_finished", {
          tool: state.current_action,
          action_number: state.actions_used,
          result: { error: "cancelled" },
        });
      finish("stopped");
      return structuredClone(state);
    }
    if (state.status !== "running") return structuredClone(state);
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
      const inputTokens = 120 + step * 7;
      const outputTokens = 28 + step * 3;
      const webSearchRequests = step === 1 ? 1 : 0;
      const amount =
        inputTokens / 1000000 +
        (outputTokens * 5) / 1000000 +
        webSearchRequests * 0.01;
      state.model_calls_used++;
      state.network_requests_used += 1 + webSearchRequests;
      state.last_request_cost = {
        model: "claude-haiku-4-5",
        currency: "USD",
        amount_usd: Number(amount.toFixed(8)),
        estimated: true,
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        cache_creation_input_tokens: 0,
        cache_read_input_tokens: 0,
        web_search_requests: webSearchRequests,
      };
      state.total_estimated_cost_usd = Number(
        (state.total_estimated_cost_usd + amount).toFixed(8),
      );
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
        result = { finding_id: "demo-finding", disposition: "created" };
        state.findings.push({
          title: "Exemple de constat — données fictives",
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
        });
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
    return structuredClone(state);
  };
};
