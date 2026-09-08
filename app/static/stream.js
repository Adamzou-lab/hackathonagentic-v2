/* Lecteur SSE : décode les trames sans interpréter leurs données comme du HTML. */
window.readLockinStream = async function (
  response,
  onEvent,
  onActivity = () => {},
) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      onActivity();
      buffer += decoder.decode(value, { stream: true });
      if (buffer.length > 1048576)
        throw new Error("Trame de suivi trop volumineuse.");
      for (;;) {
        const separator = /\r?\n\r?\n/.exec(buffer);
        if (!separator) break;
        const block = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator[0].length);
        let type = "message";
        const lines = [];
        for (const line of block.split(/\r?\n/)) {
          if (line.startsWith("event:")) type = line.slice(6).trim();
          if (line.startsWith("data:"))
            lines.push(line.slice(5).replace(/^ /, ""));
        }
        if (!lines.length || !["journal", "draft", "end"].includes(type))
          continue;
        if ((await onEvent(type, JSON.parse(lines.join("\n")))) === false)
          return;
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
};
