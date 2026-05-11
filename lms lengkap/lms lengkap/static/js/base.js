/* ====================================================================
   base.js - Interaksi global (sidebar mobile, dropdown, polling chat).
   ==================================================================== */

document.addEventListener("DOMContentLoaded", () => {
    // Hamburger toggle untuk sidebar di mobile
    const toggle = document.getElementById("sb-toggle");
    const sidebar = document.getElementById("sidebar");
    const backdrop = document.getElementById("sb-backdrop");
    if (toggle && sidebar) {
        toggle.addEventListener("click", () => {
            sidebar.classList.toggle("open");
            if (backdrop) backdrop.classList.toggle("show");
        });
    }
    if (backdrop && sidebar) {
        backdrop.addEventListener("click", () => {
            sidebar.classList.remove("open");
            backdrop.classList.remove("show");
        });
    }

    // Tutup user menu jika klik di luar
    const um = document.getElementById("user-menu");
    if (um) {
        document.addEventListener("click", (e) => {
            if (!um.contains(e.target)) um.classList.remove("open");
        });
    }
});
