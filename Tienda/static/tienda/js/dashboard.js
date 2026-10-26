(function () {
  'use strict';

  var root = document.documentElement;
  var storedTheme = localStorage.getItem('ampere-dashboard-theme');
  if (storedTheme === 'dark' || storedTheme === 'light') root.dataset.theme = storedTheme;

  function themeColors() {
    var styles = getComputedStyle(root);
    return {
      ink: styles.getPropertyValue('--ink').trim(),
      muted: styles.getPropertyValue('--muted').trim(),
      line: styles.getPropertyValue('--line').trim(),
      purple: styles.getPropertyValue('--purple').trim(),
      surface: styles.getPropertyValue('--surface').trim()
    };
  }

  var themeToggle = document.getElementById('theme-toggle');
  function updateThemeIcon() {
    var icon = document.querySelector('.theme-icon');
    if (icon) icon.textContent = root.dataset.theme === 'dark' ? '☀' : '☾';
  }
  updateThemeIcon();
  if (themeToggle) themeToggle.addEventListener('click', function () {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('ampere-dashboard-theme', root.dataset.theme);
    updateThemeIcon();
    drawAllCharts();
  });

  var sidebar = document.getElementById('seller-sidebar');
  var scrim = document.getElementById('sidebar-scrim');
  function setSidebar(open) {
    sidebar.classList.toggle('open', open);
    scrim.classList.toggle('open', open);
  }
  document.getElementById('sidebar-open').addEventListener('click', function () { setSidebar(true); });
  document.getElementById('sidebar-close').addEventListener('click', function () { setSidebar(false); });
  scrim.addEventListener('click', function () { setSidebar(false); });
  document.querySelectorAll('.seller-nav a[href^="#"]').forEach(function (link) {
    link.addEventListener('click', function () { setSidebar(false); });
  });

  function bindPeriodControl() {
    var periodSelect = document.getElementById('period-select');
    var periodForm = document.getElementById('period-form');
    if (!periodSelect || !periodForm || periodSelect.dataset.bound === 'true') return;
    periodSelect.dataset.bound = 'true';
    periodSelect.addEventListener('change', function () {
      var customDates = periodForm.querySelector('.custom-dates');
      if (this.value === 'personalizado') {
        customDates.hidden = false;
        customDates.querySelector('input').focus();
      } else {
        customDates.hidden = true;
        periodForm.submit();
      }
    });
  }
  bindPeriodControl();

  var searchInput = document.querySelector('.global-search input[name="q"]');
  document.addEventListener('keydown', function (event) {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      searchInput.focus();
    }
    if (event.key === 'Escape') {
      closeModals();
      setSidebar(false);
    }
  });

  var notificationButton = document.getElementById('notification-button');
  var notificationPanel = document.getElementById('notification-panel');
  var markRead = document.getElementById('mark-read');
  function applyReadState() {
    var read = localStorage.getItem('ampere-notifications-read') === 'true';
    document.querySelectorAll('.notification-item').forEach(function (item) { item.classList.toggle('unread', !read); });
    var dot = document.querySelector('.notification-dot');
    if (dot) dot.hidden = read;
    var count = document.getElementById('notification-count');
    if (count) count.textContent = read ? 'Todo al día' : document.querySelectorAll('.notification-item').length + ' sin leer';
  }
  applyReadState();
  notificationButton.addEventListener('click', function (event) {
    event.stopPropagation();
    notificationPanel.hidden = !notificationPanel.hidden;
    notificationButton.setAttribute('aria-expanded', String(!notificationPanel.hidden));
  });
  markRead.addEventListener('click', function () {
    localStorage.setItem('ampere-notifications-read', 'true');
    applyReadState();
  });
  document.addEventListener('click', function (event) {
    if (!notificationPanel.contains(event.target) && event.target !== notificationButton) {
      notificationPanel.hidden = true;
      notificationButton.setAttribute('aria-expanded', 'false');
    }
  });

  document.querySelectorAll('.toast button').forEach(function (button) {
    button.addEventListener('click', function () { button.parentElement.remove(); });
  });
  window.setTimeout(function () {
    document.querySelectorAll('.toast').forEach(function (toast) { toast.remove(); });
  }, 6500);

  function showToast(message) {
    var stack = document.querySelector('.toast-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'toast-stack';
      document.querySelector('.dashboard-content').prepend(stack);
    }
    var toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = '<span></span><button type="button" aria-label="Cerrar">×</button>';
    toast.querySelector('span').textContent = message;
    toast.querySelector('button').addEventListener('click', function () { toast.remove(); });
    stack.appendChild(toast);
    window.setTimeout(function () { toast.remove(); }, 4000);
  }
  document.querySelectorAll('[data-coming-soon]').forEach(function (link) {
    link.addEventListener('click', function (event) {
      event.preventDefault();
      showToast(link.dataset.comingSoon + ' estará disponible próximamente.');
    });
  });

  var activeModal = null;
  function openModal(id) {
    var modal = document.getElementById('order-modal-' + id);
    if (!modal) return;
    modal.hidden = false;
    activeModal = modal;
    document.body.classList.add('modal-open');
    var closeButton = modal.querySelector('[data-close-modal]');
    if (closeButton) closeButton.focus();
  }
  function closeModals() {
    document.querySelectorAll('.order-modal:not([hidden])').forEach(function (modal) { modal.hidden = true; });
    activeModal = null;
    document.body.classList.remove('modal-open');
  }
  function bindOrderControls() {
    document.querySelectorAll('.open-order:not([data-live-bound])').forEach(function (button) {
      button.dataset.liveBound = 'true';
      button.addEventListener('click', function (event) { event.stopPropagation(); openModal(button.dataset.order); });
    });
    document.querySelectorAll('.orders-table tbody tr[data-order]:not([data-live-bound])').forEach(function (row) {
      row.dataset.liveBound = 'true';
      row.addEventListener('dblclick', function () { openModal(row.dataset.order); });
      row.addEventListener('keydown', function (event) { if (event.key === 'Enter') openModal(row.dataset.order); });
    });
    document.querySelectorAll('[data-close-modal]:not([data-live-bound])').forEach(function (element) {
      element.dataset.liveBound = 'true';
      element.addEventListener('click', closeModals);
    });
  }
  bindOrderControls();

  function jsonData(id, sourceDocument) {
    var node = (sourceDocument || document).getElementById(id);
    try { return node ? JSON.parse(node.textContent) : []; } catch (error) { return []; }
  }
  var salesData = jsonData('sales-series');
  var shippingData = jsonData('shipping-data');
  var shippingMapData = jsonData('shipping-map-data');
  var categoryData = jsonData('category-data');
  var chartColors = ['#6d5ce7', '#ed8a34', '#3b82f6', '#18a875', '#dc5570'];

  function initShippingMap() {
    var container = document.getElementById('seller-shipping-map');
    if (!container) return;
    if (!window.L) {
      container.classList.add('map-unavailable');
      container.textContent = 'El mapa necesita conexión a internet. Los datos de envío siguen disponibles en cada pedido.';
      return;
    }
    var map = L.map(container, { scrollWheelZoom: false }).setView([-34.6037, -58.3816], 11);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(map);
    var bounds = [];
    shippingMapData.forEach(function (shipment) {
      var point = [Number(shipment.lat), Number(shipment.lng)];
      if (!Number.isFinite(point[0]) || !Number.isFinite(point[1])) return;
      bounds.push(point);
      var popup = document.createElement('div');
      var title = document.createElement('strong');
      title.textContent = shipment.codigo + ' · ' + shipment.estado;
      var address = document.createElement('p');
      address.textContent = shipment.direccion || 'Dirección no registrada';
      popup.appendChild(title);
      popup.appendChild(address);
      if (shipment.tracking) {
        var tracking = document.createElement('small');
        tracking.textContent = (shipment.transportista || 'Seguimiento') + ': ' + shipment.tracking;
        popup.appendChild(tracking);
      }
      var marker = L.marker(point, { title: 'Pedido ' + shipment.codigo }).addTo(map).bindPopup(popup);
      marker.on('click', function () {
        var modal = document.getElementById('order-modal-' + shipment.id);
        if (modal) marker.getPopup().getElement().addEventListener('dblclick', function () { openModal(shipment.id); }, { once: true });
      });
    });
    if (bounds.length === 1) map.setView(bounds[0], 14);
    else if (bounds.length > 1) map.fitBounds(bounds, { padding: [28, 28], maxZoom: 14 });
  }
  initShippingMap();

  function prepareCanvas(canvas) {
    var rect = canvas.getBoundingClientRect();
    var ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, Math.floor(rect.width * ratio));
    canvas.height = Math.max(1, Math.floor(rect.height * ratio));
    var context = canvas.getContext('2d');
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    return { ctx: context, width: rect.width, height: rect.height };
  }

  function compactMoney(value) {
    return new Intl.NumberFormat('es-AR', { notation: value >= 100000 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(value);
  }

  function drawSalesChart() {
    var canvas = document.getElementById('sales-chart');
    if (!canvas) return;
    var box = prepareCanvas(canvas), ctx = box.ctx, width = box.width, height = box.height;
    var colors = themeColors();
    var pad = { left: 44, right: 14, top: 14, bottom: 30 };
    var values = salesData.map(function (item) { return Number(item.value) || 0; });
    var max = Math.max.apply(null, values.concat([1]));
    ctx.clearRect(0, 0, width, height);
    ctx.font = '9px Inter';
    ctx.textBaseline = 'middle';
    for (var tick = 0; tick <= 4; tick += 1) {
      var y = pad.top + (height - pad.top - pad.bottom) * tick / 4;
      ctx.strokeStyle = colors.line;
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
      ctx.fillStyle = colors.muted;
      ctx.textAlign = 'right';
      ctx.fillText('$' + compactMoney(max * (1 - tick / 4)), pad.left - 8, y);
    }
    if (!salesData.length || values.every(function (value) { return value === 0; })) {
      canvas.nextElementSibling.hidden = false;
    } else {
      canvas.nextElementSibling.hidden = true;
    }
    if (!salesData.length) return;
    var innerWidth = width - pad.left - pad.right;
    var innerHeight = height - pad.top - pad.bottom;
    var points = salesData.map(function (item, index) {
      return { x: pad.left + (salesData.length === 1 ? innerWidth / 2 : innerWidth * index / (salesData.length - 1)), y: pad.top + innerHeight * (1 - (Number(item.value) || 0) / max) };
    });
    var gradient = ctx.createLinearGradient(0, pad.top, 0, height - pad.bottom);
    gradient.addColorStop(0, 'rgba(109,92,231,.28)'); gradient.addColorStop(1, 'rgba(109,92,231,0)');
    ctx.beginPath(); ctx.moveTo(points[0].x, height - pad.bottom); points.forEach(function (point) { ctx.lineTo(point.x, point.y); }); ctx.lineTo(points[points.length - 1].x, height - pad.bottom); ctx.closePath(); ctx.fillStyle = gradient; ctx.fill();
    ctx.beginPath(); points.forEach(function (point, index) { if (index === 0) ctx.moveTo(point.x, point.y); else ctx.lineTo(point.x, point.y); }); ctx.strokeStyle = colors.purple; ctx.lineWidth = 2.3; ctx.lineJoin = 'round'; ctx.stroke();
    points.forEach(function (point) { ctx.beginPath(); ctx.arc(point.x, point.y, 3, 0, Math.PI * 2); ctx.fillStyle = colors.surface; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = colors.purple; ctx.stroke(); });
    ctx.fillStyle = colors.muted; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    var labelStep = Math.max(1, Math.ceil(salesData.length / 7));
    salesData.forEach(function (item, index) { if (index % labelStep === 0 || index === salesData.length - 1) ctx.fillText(item.label, points[index].x, height - pad.bottom + 10); });
  }

  function drawOrdersChart() {
    var canvas = document.getElementById('orders-chart');
    if (!canvas) return;
    var box = prepareCanvas(canvas), ctx = box.ctx, width = box.width, height = box.height;
    var total = shippingData.reduce(function (sum, item) { return sum + Number(item.value || 0); }, 0);
    var centerX = width / 2, centerY = height / 2, radius = Math.min(width, height) / 2 - 8;
    ctx.clearRect(0, 0, width, height);
    var start = -Math.PI / 2;
    if (!total) {
      ctx.beginPath(); ctx.arc(centerX, centerY, radius, 0, Math.PI * 2); ctx.strokeStyle = themeColors().line; ctx.lineWidth = 18; ctx.stroke();
    } else {
      shippingData.forEach(function (item, index) {
        var angle = Number(item.value || 0) / total * Math.PI * 2;
        if (!angle) return;
        ctx.beginPath(); ctx.arc(centerX, centerY, radius, start + .025, start + angle - .025); ctx.strokeStyle = chartColors[index]; ctx.lineWidth = 18; ctx.lineCap = 'round'; ctx.stroke();
        start += angle;
      });
    }
    var legend = document.getElementById('orders-legend');
    legend.innerHTML = '';
    shippingData.forEach(function (item, index) {
      var row = document.createElement('div'); row.className = 'legend-row';
      var dot = document.createElement('i'); dot.style.background = chartColors[index];
      var label = document.createElement('span'); label.textContent = item.label;
      var value = document.createElement('strong'); value.textContent = item.value;
      row.append(dot, label, value); legend.appendChild(row);
    });
  }

  function drawCategoryBars() {
    var container = document.getElementById('category-chart');
    if (!container) return;
    container.innerHTML = '';
    var max = Math.max.apply(null, categoryData.map(function (item) { return Number(item.value); }).concat([1]));
    if (!categoryData.length) {
      container.innerHTML = '<div class="empty-mini">Todavía no hay datos por categoría.</div>';
      return;
    }
    categoryData.forEach(function (item) {
      var row = document.createElement('div'); row.className = 'bar-row';
      var label = document.createElement('span'); label.textContent = item.label;
      var track = document.createElement('div'); track.className = 'bar-track';
      var fill = document.createElement('div'); fill.className = 'bar-fill'; fill.style.width = Math.max(3, Number(item.value) / max * 100) + '%'; track.appendChild(fill);
      var value = document.createElement('strong'); value.textContent = '$' + compactMoney(Number(item.value));
      row.append(label, track, value); container.appendChild(row);
    });
  }

  function drawAllCharts() { drawSalesChart(); drawOrdersChart(); drawCategoryBars(); }
  drawAllCharts();
  var resizeTimer;
  window.addEventListener('resize', function () { window.clearTimeout(resizeTimer); resizeTimer = window.setTimeout(drawAllCharts, 100); });

  var websocketPath = document.body.dataset.websocketUrl;
  var liveRevision = document.body.dataset.liveRevision;
  var liveRefreshRunning = false;
  var pendingRevision = null;
  var pendingRefreshForced = false;
  var dashboardSocket = null;
  var reconnectTimer = null;
  var reconnectDelay = 1000;

  function setLiveStatus(state, text) {
    var status = document.getElementById('live-sync');
    if (!status) return;
    status.classList.toggle('refreshing', state === 'refreshing');
    status.classList.toggle('offline', state === 'offline');
    var label = status.lastChild;
    if (label && label.nodeType === Node.TEXT_NODE) label.textContent = ' ' + text;
  }

  function dashboardIsBusy() {
    var focused = document.activeElement;
    var editable = focused && ['INPUT', 'SELECT', 'TEXTAREA'].indexOf(focused.tagName) !== -1;
    return document.hidden || editable || Boolean(document.querySelector('.order-modal:not([hidden])'));
  }

  function replaceDashboard(html, revision) {
    var parsed = new DOMParser().parseFromString(html, 'text/html');
    var incomingContent = parsed.querySelector('.dashboard-content');
    var currentContent = document.querySelector('.dashboard-content');
    if (!incomingContent || !currentContent) throw new Error('Respuesta del panel incompleta');

    currentContent.replaceWith(document.importNode(incomingContent, true));
    document.querySelectorAll('.order-modal').forEach(function (modal) { modal.remove(); });
    parsed.querySelectorAll('.order-modal').forEach(function (modal) {
      document.body.appendChild(document.importNode(modal, true));
    });

    var incomingBadge = parsed.querySelector('.nav-badge');
    var currentBadge = document.querySelector('.nav-badge');
    if (incomingBadge && currentBadge) currentBadge.textContent = incomingBadge.textContent;

    salesData = jsonData('sales-series', parsed);
    shippingData = jsonData('shipping-data', parsed);
    categoryData = jsonData('category-data', parsed);
    liveRevision = parsed.body.dataset.liveRevision || revision;
    document.body.dataset.liveRevision = liveRevision;
    activeModal = null;
    document.body.classList.remove('modal-open');
    bindPeriodControl();
    bindOrderControls();
    drawAllCharts();
  }

  async function refreshDashboard(revision, force) {
    if (liveRefreshRunning || (!force && revision === liveRevision)) return;
    if (dashboardIsBusy()) {
      pendingRevision = revision;
      pendingRefreshForced = pendingRefreshForced || force;
      window.setTimeout(flushPendingRefresh, 1000);
      return;
    }
    liveRefreshRunning = true;
    try {
      setLiveStatus('refreshing', 'Actualizando…');
      var pageResponse = await fetch(window.location.href, {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { 'X-Dashboard-Refresh': '1' }
      });
      if (pageResponse.redirected) {
        window.location.assign(pageResponse.url);
        return;
      }
      if (!pageResponse.ok) throw new Error('No se pudo actualizar el panel');
      replaceDashboard(await pageResponse.text(), revision);
      setLiveStatus('ready', 'Conectado en tiempo real');
      showToast('Nueva compra recibida. El panel se actualizó automáticamente.');
    } catch (error) {
      setLiveStatus('offline', 'Reconectando…');
    } finally {
      liveRefreshRunning = false;
    }
  }

  function flushPendingRefresh() {
    if (!pendingRevision || liveRefreshRunning) return;
    if (dashboardIsBusy()) {
      window.setTimeout(flushPendingRefresh, 1000);
      return;
    }
    var revision = pendingRevision;
    var force = pendingRefreshForced;
    pendingRevision = null;
    pendingRefreshForced = false;
    refreshDashboard(revision, force);
  }

  function scheduleReconnect() {
    if (reconnectTimer || document.hidden) return;
    setLiveStatus('offline', 'Reconectando WebSocket…');
    reconnectTimer = window.setTimeout(function () {
      reconnectTimer = null;
      connectDashboardSocket();
    }, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  }

  function connectDashboardSocket() {
    if (!websocketPath || document.hidden) return;
    if (dashboardSocket && (
      dashboardSocket.readyState === WebSocket.OPEN ||
      dashboardSocket.readyState === WebSocket.CONNECTING
    )) return;

    var socketUrl = new URL(websocketPath, window.location.href);
    socketUrl.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    dashboardSocket = new WebSocket(socketUrl.href);
    setLiveStatus('refreshing', 'Conectando WebSocket…');

    dashboardSocket.addEventListener('open', function () {
      reconnectDelay = 1000;
      setLiveStatus('ready', 'Conectado en tiempo real');
    });
    dashboardSocket.addEventListener('message', function (event) {
      var payload;
      try { payload = JSON.parse(event.data); } catch (error) { return; }
      if (payload.type === 'ping') {
        if (dashboardSocket.readyState === WebSocket.OPEN) dashboardSocket.send('ping');
        return;
      }
      if (payload.type === 'ready') {
        setLiveStatus('ready', 'Conectado en tiempo real');
      }
      if (payload.type === 'ready' && payload.revision !== liveRevision) {
        pendingRevision = payload.revision;
        flushPendingRefresh();
      }
      if (payload.type === 'sale.created' || payload.type === 'sale.updated') {
        pendingRevision = payload.revision;
        pendingRefreshForced = true;
        flushPendingRefresh();
      }
    });
    dashboardSocket.addEventListener('close', function (event) {
      dashboardSocket = null;
      if (event.code === 4403) {
        window.location.reload();
        return;
      }
      scheduleReconnect();
    });
    dashboardSocket.addEventListener('error', function () {
      if (dashboardSocket) dashboardSocket.close();
    });
  }

  if (websocketPath && 'WebSocket' in window) {
    connectDashboardSocket();
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) {
        connectDashboardSocket();
        flushPendingRefresh();
      }
    });
  } else {
    setLiveStatus('offline', 'WebSocket no disponible');
  }
})();
