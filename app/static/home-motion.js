/* Illustration d'accueil uniquement : aucun appel à l'API de recherche. */
(() => {
  "use strict";
  const scene = document.querySelector(".lk-home-motion");
  if (!scene) return;
  const q = (selector) => scene.querySelector(selector);
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  let animations = [];
  let started = false;
  let observer;
  let origin = null;

  // Une même horloge synchronise les feuilles, la loupe et le clin d'œil.
  // Les positions sont calculées une fois ; le navigateur anime ensuite les
  // transformations et l'opacité, sans boucle JavaScript à chaque image.
  const duration = 4200;
  const clamp = (value) => Math.max(0, Math.min(1, value));
  const smooth = (value) => {
    const t = clamp(value);
    return t * t * t * (t * (t * 6 - 15) + 10);
  };
  const mix = (a, b, t) => a + (b - a) * t;
  const phase = (time, start, length) => smooth((time - start) / length);
  const sampled = (frame) => Array.from({ length: 127 }, (_, index) => {
    const offset = index / 126;
    return { ...frame(offset * duration), offset };
  });
  const animate = (node, frames, delay = 0, length = duration, easing = "linear") => {
    const animation = node.animate(frames, {
      duration: length, delay, fill: "both", easing,
    });
    if (origin !== null) animation.startTime = origin;
    animations.push(animation);
  };
  const ease = "cubic-bezier(.4,0,.2,1)";

  function finish() {
    // Le CSS conserve l'image finale ; on libère toutes les animations.
    // Un retour depuis « Mes veilles » ne rejoue pas la séquence.
    started = true;
    observer?.disconnect();
    scene.dataset.motion = "finished";
    animations.forEach((animation) => animation.cancel());
    animations = [];
  }

  function playIntro() {
    if (started) return;
    started = true;
    observer?.disconnect();
    if (reduced.matches || typeof scene.animate !== "function") {
      finish();
      return;
    }
    scene.dataset.motion = "playing";
    origin = document.timeline.currentTime;
    try {
      const docs = [
        [".lk-motion-paper-a", -11, 11, 78.5],
        [".lk-motion-paper-b", 9, -133, 89.5],
        [".lk-motion-paper-c", -6, -132, -22.5],
      ];
      docs.forEach(([selector, rotation, dx, dy], index) => {
        animate(q(selector), sampled((time) => {
          // Les raccords ont une vitesse et une accélération nulles : les
          // feuilles arrivent puis convergent sans changement brutal de cap.
          const enter = phase(time, 100 + index * 140, 820);
          const gather = phase(time, 2110 + index * 90, 1110);
          const drift = Math.sin(Math.PI * clamp((time - 940) / 1150)) ** 2;
          const arc = Math.sin(Math.PI * gather);
          const x = (index ? 8 : -8) * (1 - enter) + dx * gather + (index === 0 ? -12 : 14) * arc;
          const y = 14 * (1 - enter) - 2.5 * drift * (1 - gather) + dy * gather - 14 * arc;
          const angle = mix(rotation - 3 * (1 - enter), -8, gather);
          return {
            opacity: enter * (1 - phase(time, 2780 + index * 90, 530)),
            transform: `translate3d(${x}px,${y}px,0) rotate(${angle}deg) scale(${mix(.88, 1, enter) - .08 * gather})`,
          };
        }));
        animate(q(selector + " em"), [{ background: "#d3cbb8" }, { background: "#e88e68" }], 1100 + index * 270, 550, ease);
      });
      animate(q(".lk-motion-character"), sampled((time) => {
        const t = clamp(time / 3650);
        const envelope = Math.sin(Math.PI * t) ** 2;
        const angle = -3 * Math.sin(2 * Math.PI * t) * envelope;
        return { transform: `translate3d(0,${-1.8 * envelope}px,0) rotate(${angle}deg)` };
      }));
      animate(q(".lk-motion-shine b"), sampled((time) => {
        const t = clamp((time - 1100) / 1050);
        return { opacity: .4 * Math.sin(Math.PI * t) ** 2, transform: `translateX(${200 * smooth(t)}px) rotate(25deg)` };
      }));
      animate(q(".lk-motion-orbit"), sampled((time) => {
        const t = clamp((time - 800) / 1650);
        return { opacity: .45 * Math.sin(Math.PI * t) ** 2, transform: `scale(${mix(.84, 1.2, smooth(t))})` };
      }));
      animate(q(".lk-motion-summary"), [
        { opacity: 0, transform: "translate3d(4px,5px,0) scale(.9) rotate(-10deg)" },
        { opacity: 1, transform: "translate3d(0,0,0) scale(1) rotate(-8deg)" },
      ], 3010, 650, ease);
      animate(q(".lk-motion-summary-icon"), [{ opacity: 0, transform: "scale(.8)" }, { opacity: 1, transform: "scale(1)" }], 3490, 460, ease);
      // Le corps et la monture restent ceux du sprite de repos. Seul le
      // visage masqué apparaît, sans redimensionner ni déplacer la loupe.
      animate(q(".lk-motion-wink"), [{ opacity: 0 }, { opacity: 1 }], 3260, 440, ease);
      animate(q(".lk-motion-twinkle"), sampled((time) => {
        const pulse = Math.sin(Math.PI * clamp((time - 3550) / 650)) ** 2;
        return { opacity: .8 * pulse, transform: `scale(${.4 + .6 * pulse})` };
      }));
      Promise.all(animations.map((animation) => animation.finished)).then(finish, finish);
    } catch {
      // Une illustration indisponible ne doit jamais empêcher une recherche.
      finish();
    }
  }

  const topic = document.getElementById("lk-topic");
  topic?.addEventListener("focus", () => {
    if (!reduced.matches && scene.dataset.motion === "finished") scene.classList.add("lk-motion-focused");
  });
  topic?.addEventListener("blur", () => scene.classList.remove("lk-motion-focused"));
  reduced.addEventListener("change", () => {
    scene.classList.remove("lk-motion-focused");
    if (reduced.matches) finish();
  });

  // Attendre les sprites et la visibilité réelle avant la lecture unique.
  // Aucune requête de veille n'est déclenchée par cette mise en scène.
  const assets = Array.from(scene.querySelectorAll("img"));
  Promise.all(assets.map((image) => image.decode().catch(() => {}))).then(() => {
    if (started) return;
    if (reduced.matches || !("IntersectionObserver" in window)) {
      playIntro();
      return;
    }
    observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) playIntro();
    }, { threshold: .4 });
    observer.observe(scene);
  });
})();
