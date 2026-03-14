/**
 * ab-test.js — Client-side A/B test variant switcher for /signup
 *
 * Uses text-matching instead of CSS selectors because most Webflow elements
 * lack unique data-w-id attributes in the rendered DOM.
 *
 * How it works:
 * 1. Fetches variant-config.json from GitHub
 * 2. Assigns visitor to baseline (50%) or challenger (50%) via cookie
 * 3. Tags GA4 with hg_variant user property
 * 4. For challenger visitors, finds elements by baseline text and swaps to challenger text
 *
 * Safety: If fetch fails or config is missing, page shows baseline unchanged.
 */
(function () {
  var CONFIG_URL =
    "https://raw.githubusercontent.com/evan-netizen-1/landing-page-optimizer/main/data/variant-config.json";

  function getCookie(name) {
    var match = document.cookie.match(
      new RegExp("(^| )" + name + "=([^;]+)")
    );
    return match ? match[2] : null;
  }

  function setCookie(name, value, days) {
    var d = new Date();
    d.setTime(d.getTime() + days * 86400000);
    document.cookie =
      name + "=" + value + ";path=/;expires=" + d.toUTCString() + ";SameSite=Lax";
  }

  function findAndReplace(baselineText, newText) {
    // Normalize whitespace for comparison
    var needle = baselineText.replace(/\s+/g, " ").trim();
    var els = document.querySelectorAll("h1, h2, h3, div");
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      // Match leaf-ish elements (skip containers with many children)
      if (el.children.length > 3) continue;
      var elText = el.textContent.replace(/\s+/g, " ").trim();
      if (elText === needle) {
        if (newText.indexOf("<br") !== -1) {
          el.innerHTML = newText;
        } else {
          el.textContent = newText;
        }
        return true;
      }
    }
    return false;
  }

  fetch(CONFIG_URL + "?t=" + Date.now())
    .then(function (r) { return r.json(); })
    .then(function (cfg) {
      if (!cfg || !cfg.experiment_id) return;

      var variant = getCookie("hg_variant");
      var experimentId = getCookie("hg_experiment_id");

      if (experimentId !== cfg.experiment_id) {
        variant = null;
      }

      if (!variant) {
        variant = Math.random() < 0.5 ? "baseline" : "challenger";
        setCookie("hg_variant", variant, 30);
        setCookie("hg_experiment_id", cfg.experiment_id, 30);
      }

      // Tag GA4 with variant — try gtag first, fall back to dataLayer
      if (window.gtag) {
        gtag("set", "user_properties", { hg_variant: variant });
      } else if (window.dataLayer) {
        window.dataLayer.push({
          event: "hg_variant_set",
          hg_variant: variant
        });
      }

      // Swap text for challenger visitors
      if (variant === "challenger" && cfg.swaps) {
        for (var i = 0; i < cfg.swaps.length; i++) {
          var swap = cfg.swaps[i];
          findAndReplace(swap.baseline, swap.challenger);
        }
      }
    })
    .catch(function () {
      /* fail silently — page shows baseline */
    });
})();
