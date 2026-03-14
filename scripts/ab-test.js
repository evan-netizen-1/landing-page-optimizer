/**
 * ab-test.js — Client-side A/B test variant switcher for /signup
 *
 * How it works:
 * 1. Fetches variant-config.json from GitHub (raw.githubusercontent.com)
 * 2. Assigns visitor to baseline (50%) or challenger (50%) via cookie
 * 3. Tags GA4 with hg_variant user property for analytics segmentation
 * 4. For challenger visitors, swaps text on targeted DOM elements
 *
 * Safety: If fetch fails, script errors, or config is missing,
 * the page renders as-is (baseline). Zero risk of breaking the page.
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

  fetch(CONFIG_URL + "?t=" + Date.now())
    .then(function (r) {
      return r.json();
    })
    .then(function (cfg) {
      if (!cfg || !cfg.experiment_id) return;

      var variant = getCookie("hg_variant");
      var experimentId = getCookie("hg_experiment_id");

      // Reset assignment if experiment changed
      if (experimentId !== cfg.experiment_id) {
        variant = null;
      }

      if (!variant) {
        variant = Math.random() < 0.5 ? "baseline" : "challenger";
        setCookie("hg_variant", variant, 30);
        setCookie("hg_experiment_id", cfg.experiment_id, 30);
      }

      // Tag GA4 with variant
      if (window.gtag) {
        gtag("set", "user_properties", { hg_variant: variant });
      }

      // Swap text for challenger visitors
      if (variant === "challenger" && cfg.challenger && cfg.selectors) {
        var s = cfg.selectors;
        var c = cfg.challenger;
        for (var key in s) {
          if (c[key] !== undefined) {
            var el = document.querySelector(s[key]);
            if (el) {
              // Use innerHTML if value contains <br> for line breaks
              if (c[key].indexOf("<br") !== -1) {
                el.innerHTML = c[key];
              } else {
                el.textContent = c[key];
              }
            }
          }
        }
      }
    })
    .catch(function () {
      /* fail silently — page shows baseline */
    });
})();
