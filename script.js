document.querySelectorAll("[data-scroll]").forEach(btn => {
  btn.addEventListener("click", () => {
    const target = document.querySelector(btn.dataset.scroll);
    if (target) target.scrollIntoView({behavior:"smooth", block:"start"});
  });
});

document.querySelectorAll(".side-link").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".side-link").forEach(x => x.classList.remove("active"));
    btn.classList.add("active");
  });
});
