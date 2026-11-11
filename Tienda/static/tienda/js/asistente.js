(function () {
  'use strict';
  var root = document.getElementById('store-assistant');
  if (!root) return;
  var launcher = document.getElementById('assistant-launcher');
  var panel = document.getElementById('assistant-panel');
  var close = document.getElementById('assistant-close');
  var form = document.getElementById('assistant-form');
  var messages = document.getElementById('assistant-messages');
  var messageInput = document.getElementById('assistant-message');
  var storageKey = 'amp-assistant-state-v1:' + (root.dataset.stateScope || 'guest');
  var state = { open: false, messages: [] };

  function readState() {
    try {
      var saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
      if (saved && typeof saved.open === 'boolean' && Array.isArray(saved.messages)) {
        state.open = saved.open;
        state.messages = saved.messages.slice(-40).filter(function (item) {
          return item && ['bot', 'customer', 'error'].indexOf(item.kind) !== -1 && typeof item.text === 'string';
        });
      }
    } catch (_error) {
      state = { open: false, messages: [] };
    }
  }

  function saveState() {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(state));
    } catch (_error) {
      // El asistente sigue funcionando aunque el navegador bloquee el almacenamiento.
    }
  }

  function cleanAssistantText(text) {
    return String(text == null ? '' : text)
      .replace(/```(?:\w+)?\s*([\s\S]*?)```/g, '$1')
      .replace(/`([^`\n]+)`/g, '$1')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/^\s{0,3}#{1,6}\s+/gm, '')
      .replace(/^\s*[*+]\s+/gm, '- ')
      .replace(/^>\s?/gm, '')
      .replace(/(\*\*|__)(.*?)\1/g, '$2')
      .replace(/(\*|_)([^*_\n]+)\1/g, '$2')
      .replace(/\*/g, '')
      .trim();
  }

  function appendMessage(kind, text, persist) {
    var bubble = document.createElement('p');
    bubble.className = 'assistant-bubble ' + (kind === 'customer' ? 'customer' : 'bot');
    if (kind === 'error') bubble.classList.add('error');
    var displayText = kind === 'bot' ? cleanAssistantText(text) : text;
    bubble.textContent = displayText;
    messages.appendChild(bubble);
    messages.scrollTop = messages.scrollHeight;
    if (persist !== false) {
      state.messages.push({ kind: kind, text: displayText });
      state.messages = state.messages.slice(-40);
      saveState();
    }
  }

  function restoreMessages() {
    if (!state.messages.length) return;
    messages.replaceChildren();
    state.messages.forEach(function (item) {
      appendMessage(item.kind, item.text, false);
    });
  }

  function setOpen(open, focusPanel) {
    panel.hidden = !open;
    launcher.setAttribute('aria-expanded', String(open));
    state.open = open;
    saveState();
    if (open && focusPanel !== false) panel.querySelector('button').focus();
  }
  launcher.addEventListener('click', function () { setOpen(panel.hidden); });
  close.addEventListener('click', function () { setOpen(false); launcher.focus(); });

  readState();
  restoreMessages();
  setOpen(state.open, false);

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var selected = event.submitter;
    var submitButton = selected || document.getElementById('assistant-send');
    var isIntent = selected && selected.name === 'intent' && selected.value;
    var customerText = isIntent ? selected.textContent.trim() : messageInput.value.trim();
    if (!customerText) {
      messageInput.focus();
      return;
    }

    var history = state.messages.filter(function (item) {
      return item.kind === 'customer' || item.kind === 'bot';
    }).slice(-12).map(function (item) {
      return {
        role: item.kind === 'customer' ? 'user' : 'assistant',
        content: item.text
      };
    });
    appendMessage('customer', customerText);
    submitButton.disabled = true;

    var data = new FormData(form);
    data.delete('message');
    if (isIntent) {
      data.set('intent', selected.value);
    } else {
      data.delete('intent');
      data.set('message', customerText);
      data.set('history', JSON.stringify(history));
      messageInput.value = '';
    }
    panel.setAttribute('aria-busy', 'true');
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
      appendMessage('bot', payload.answer);
    }).catch(function (error) {
      appendMessage('error', error.message);
    }).finally(function () {
      submitButton.disabled = false;
      panel.removeAttribute('aria-busy');
      if (!isIntent) messageInput.focus();
    });
  });
})();
