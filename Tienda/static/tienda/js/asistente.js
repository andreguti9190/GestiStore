(function () {
  'use strict';
  var root = document.getElementById('store-assistant');
  if (!root) return;
  var launcher = document.getElementById('assistant-launcher');
  var panel = document.getElementById('assistant-panel');
  var close = document.getElementById('assistant-close');
  var form = document.getElementById('assistant-form');
  var messages = document.getElementById('assistant-messages');

  function setOpen(open) {
    panel.hidden = !open;
    launcher.setAttribute('aria-expanded', String(open));
    if (open) panel.querySelector('button').focus();
  }
  launcher.addEventListener('click', function () { setOpen(panel.hidden); });
  close.addEventListener('click', function () { setOpen(false); launcher.focus(); });

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var selected = event.submitter;
    if (!selected || !selected.value) return;
    var customer = document.createElement('p');
    customer.className = 'assistant-bubble customer';
    customer.textContent = selected.textContent;
    messages.appendChild(customer);
    selected.disabled = true;

    var data = new FormData(form);
    data.set('intent', selected.value);
    fetch(root.dataset.url, {
      method: 'POST',
      body: data,
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (response) {
      return response.json().then(function (payload) {
        if (!response.ok) throw new Error(payload.error || 'No pude responder esa consulta.');
        return payload;
      });
    }).then(function (payload) {
      var bot = document.createElement('p');
      bot.className = 'assistant-bubble bot';
      bot.textContent = payload.answer;
      messages.appendChild(bot);
      messages.scrollTop = messages.scrollHeight;
    }).catch(function (error) {
      var bot = document.createElement('p');
      bot.className = 'assistant-bubble bot error';
      bot.textContent = error.message;
      messages.appendChild(bot);
    }).finally(function () {
      selected.disabled = false;
    });
  });
})();
