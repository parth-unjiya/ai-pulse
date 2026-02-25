/**
 * AI Pulse — Main JavaScript
 * Handles dark mode, reading progress, smooth scroll, and card animations.
 * Vanilla JS, no dependencies.
 */

(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // 1. Dark Mode Toggle
  // ---------------------------------------------------------------------------

  const THEME_KEY = "ai-pulse-theme";
  const root = document.documentElement;
  const toggle = document.getElementById("theme-toggle");

  /**
   * Apply the given theme ("light" or "dark") to the page and persist it.
   */
  function setTheme(theme) {
    root.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_KEY, theme);

    if (toggle) {
      toggle.setAttribute(
        "aria-label",
        theme === "dark" ? "Switch to light mode" : "Switch to dark mode"
      );
    }
  }

  /**
   * Determine the initial theme: saved preference > system preference > light.
   */
  function getInitialTheme() {
    var saved = localStorage.getItem(THEME_KEY);
    if (saved === "dark" || saved === "light") {
      return saved;
    }
    if (
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
    ) {
      return "dark";
    }
    return "light";
  }

  // Apply immediately (before paint) to avoid flash.
  setTheme(getInitialTheme());

  if (toggle) {
    toggle.addEventListener("click", function () {
      var current = root.getAttribute("data-theme");
      setTheme(current === "dark" ? "light" : "dark");
    });
  }

  // React to OS-level theme changes while the page is open.
  if (window.matchMedia) {
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", function (e) {
        // Only follow the OS if the user hasn't explicitly chosen a theme.
        if (!localStorage.getItem(THEME_KEY)) {
          setTheme(e.matches ? "dark" : "light");
        }
      });
  }

  // ---------------------------------------------------------------------------
  // 2. Reading Progress Bar (article pages only)
  // ---------------------------------------------------------------------------

  var progressBar = document.getElementById("reading-progress");
  var articleContent = document.querySelector(".article-content");

  if (progressBar && articleContent) {
    function updateProgress() {
      var scrollTop = window.scrollY || document.documentElement.scrollTop;
      var docHeight =
        document.documentElement.scrollHeight -
        document.documentElement.clientHeight;
      var progress = docHeight > 0 ? (scrollTop / docHeight) * 100 : 0;
      progressBar.style.width = Math.min(progress, 100) + "%";
    }

    window.addEventListener("scroll", updateProgress, { passive: true });
    window.addEventListener("resize", updateProgress, { passive: true });
    updateProgress();
  }

  // ---------------------------------------------------------------------------
  // 3. Smooth Scroll for Anchor Links
  // ---------------------------------------------------------------------------

  document.addEventListener("click", function (e) {
    var anchor = e.target.closest('a[href^="#"]');
    if (!anchor) return;

    var targetId = anchor.getAttribute("href");
    if (targetId === "#") return;

    var target = document.querySelector(targetId);
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: "smooth", block: "start" });

      // Update URL hash without jumping.
      if (history.pushState) {
        history.pushState(null, "", targetId);
      }
    }
  });

  // ---------------------------------------------------------------------------
  // 4. Fade-in Animation on Article Cards (IntersectionObserver)
  // ---------------------------------------------------------------------------

  function initCardAnimations() {
    var cards = document.querySelectorAll(".article-card");
    if (!cards.length) return;

    // Mark cards as hidden initially.
    cards.forEach(function (card) {
      card.classList.add("card-hidden");
    });

    if (!("IntersectionObserver" in window)) {
      // Fallback: show all immediately.
      cards.forEach(function (card) {
        card.classList.remove("card-hidden");
        card.classList.add("card-visible");
      });
      return;
    }

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.remove("card-hidden");
            entry.target.classList.add("card-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      {
        threshold: 0.1,
        rootMargin: "0px 0px -40px 0px",
      }
    );

    cards.forEach(function (card) {
      observer.observe(card);
    });
  }

  // Run once DOM is ready (script is at the end of body, so it already is).
  initCardAnimations();

  // Re-run if new cards are injected dynamically (optional future-proofing).
  if ("MutationObserver" in window) {
    var grid = document.getElementById("articles-grid");
    if (grid) {
      var mo = new MutationObserver(function (mutations) {
        var hasNewCards = mutations.some(function (m) {
          return m.addedNodes.length > 0;
        });
        if (hasNewCards) {
          initCardAnimations();
        }
      });
      mo.observe(grid, { childList: true });
    }
  }
})();
