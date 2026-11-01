/* All local workspaces share this navigation and interaction contract. */
(() => {
  const mount = document.getElementById("workspace-shell");
  if (!mount) return;
  const pages = [
    ["/", "Operations"],
    ["/restaurant-lab", "Restaurants"],
    ["/lab", "Inventory"],
    ["/health", "Health"],
    ["/agent-traces", "Traces"],
    ["/architecture", "Architecture"],
  ];
  const header = document.createElement("header");
  header.className = "workspace-header";
  const brand = document.createElement("a");
  brand.href = "/";
  brand.className = "workspace-brand";
  brand.setAttribute("aria-label", "madrid-delivery-sim home");
  brand.innerHTML =
    '<span class="workspace-wordmark">Madrid<small>Delivery sim</small></span><span class="workspace-project">madrid-delivery-sim</span>';
  brand.querySelector("small").textContent = pages.find(([path]) => path === location.pathname)?.[1] || "Operations";
  const nav = document.createElement("nav");
  nav.id = "workspace-navigation";
  nav.className = "workspace-navigation";
  nav.setAttribute("aria-label", "Workspaces");
  for (const [path, label] of pages) {
    const link = document.createElement("a");
    link.href = path;
    link.textContent = label;
    if (location.pathname === path) link.setAttribute("aria-current", "page");
    nav.append(link);
  }
  const actions = document.createElement("div");
  actions.className = "workspace-actions";
  const local = document.createElement("span");
  local.className = "workspace-local";
  local.textContent = "Local · synthetic";
  actions.append(local);
  const search = document.getElementById("open-search");
  if (search) actions.append(search);
  const menu = document.createElement("button");
  menu.type = "button";
  menu.className = "workspace-menu";
  menu.textContent = "Menu";
  menu.setAttribute("aria-controls", nav.id);
  menu.setAttribute("aria-expanded", "false");
  const closeMenu = () => {
    header.removeAttribute("data-menu-open");
    menu.setAttribute("aria-expanded", "false");
  };
  menu.addEventListener("click", () => {
    const open = menu.getAttribute("aria-expanded") !== "true";
    header.toggleAttribute("data-menu-open", open);
    menu.setAttribute("aria-expanded", String(open));
  });
  header.addEventListener("keydown", (event) => {
    if (
      event.key === "Escape" &&
      menu.getAttribute("aria-expanded") === "true"
    ) {
      closeMenu();
      menu.focus();
    }
  });
  document.addEventListener("click", (event) => {
    if (!header.contains(event.target)) closeMenu();
  });
  nav.addEventListener("click", closeMenu);
  actions.append(menu);
  header.append(brand, nav, actions);
  const skip = document.createElement("a");
  skip.className = "workspace-skip";
  skip.href =
    document.body.dataset.page === "architecture" ? "#reader" : "#main";
  skip.textContent = "Skip to workspace";
  mount.replaceChildren(skip, header);
})();
