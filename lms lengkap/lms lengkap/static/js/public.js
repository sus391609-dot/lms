/* =====================================================================
   public.js - Public website Yarsi Pratama
   Mobile drawer, scroll nav, reveal animations, counter animations.
   ===================================================================== */

(function () {
    "use strict";

    // ── Mobile drawer toggle ──────────────────────────────────────────
    var drawer = document.getElementById("uyp-drawer");
    var btnOpen = document.getElementById("uyp-hamburger");
    var btnClose = document.getElementById("uyp-drawer-close");

    function openDrawer() {
        if (!drawer) return;
        drawer.classList.add("open");
        document.body.style.overflow = "hidden";
    }
    function closeDrawer() {
        if (!drawer) return;
        drawer.classList.remove("open");
        document.body.style.overflow = "";
    }
    if (btnOpen) btnOpen.addEventListener("click", openDrawer);
    if (btnClose) btnClose.addEventListener("click", closeDrawer);
    if (drawer) {
        drawer.addEventListener("click", function (e) {
            if (e.target === drawer) closeDrawer();
        });
        // Close drawer when any internal link clicked
        Array.prototype.forEach.call(
            drawer.querySelectorAll("a"),
            function (a) { a.addEventListener("click", closeDrawer); }
        );
    }

    // ── Sticky navbar shadow on scroll ────────────────────────────────
    var nav = document.getElementById("uyp-nav");
    function onScroll() {
        if (!nav) return;
        if (window.scrollY > 16) nav.classList.add("scrolled");
        else nav.classList.remove("scrolled");
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();

    // ── Reveal-on-scroll ──────────────────────────────────────────────
    var revealItems = document.querySelectorAll(".uyp-reveal");
    if ("IntersectionObserver" in window && revealItems.length) {
        var io = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add("in");
                    io.unobserve(entry.target);
                }
            });
        }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
        revealItems.forEach(function (el) { io.observe(el); });
    } else {
        // Fallback: show immediately
        revealItems.forEach(function (el) { el.classList.add("in"); });
    }

    // ── Counter animation for stats ───────────────────────────────────
    var counters = document.querySelectorAll("[data-counter]");
    if ("IntersectionObserver" in window && counters.length) {
        var co = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                var el = entry.target;
                var target = parseInt(el.getAttribute("data-counter"), 10) || 0;
                var dur = 1100;
                var start = performance.now();
                function step(now) {
                    var p = Math.min(1, (now - start) / dur);
                    var eased = 1 - Math.pow(1 - p, 3);
                    el.textContent = Math.round(target * eased).toLocaleString("id-ID");
                    if (p < 1) requestAnimationFrame(step);
                }
                requestAnimationFrame(step);
                co.unobserve(el);
            });
        }, { threshold: 0.4 });
        counters.forEach(function (el) { co.observe(el); });
    }

    // ── Smooth-scroll for anchor links ────────────────────────────────
    Array.prototype.forEach.call(
        document.querySelectorAll('a[href^="#"]'),
        function (a) {
            a.addEventListener("click", function (e) {
                var href = a.getAttribute("href");
                if (!href || href.length < 2) return;
                var t = document.querySelector(href);
                if (!t) return;
                e.preventDefault();
                t.scrollIntoView({ behavior: "smooth", block: "start" });
            });
        }
    );
})();
