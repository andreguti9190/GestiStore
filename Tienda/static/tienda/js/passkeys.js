(function () {
  'use strict';

  function decodeBase64url(value) {
    var base64 = value.replace(/-/g, '+').replace(/_/g, '/');
    base64 += '='.repeat((4 - base64.length % 4) % 4);
    var binary = atob(base64);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
  }

  function encodeBase64url(value) {
    if (value === null || value === undefined) return null;
    var bytes = new Uint8Array(value);
    var binary = '';
    for (var i = 0; i < bytes.length; i += 0x8000) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function creationOptionsFromJSON(options) {
    options.challenge = decodeBase64url(options.challenge);
    options.user.id = decodeBase64url(options.user.id);
    (options.excludeCredentials || []).forEach(function (item) {
      item.id = decodeBase64url(item.id);
    });
    return options;
  }

  function requestOptionsFromJSON(options) {
    options.challenge = decodeBase64url(options.challenge);
    (options.allowCredentials || []).forEach(function (item) {
      item.id = decodeBase64url(item.id);
    });
    return options;
  }

  function registrationToJSON(credential) {
    return {
      id: credential.id,
      rawId: encodeBase64url(credential.rawId),
      type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment,
      clientExtensionResults: credential.getClientExtensionResults(),
      response: {
        clientDataJSON: encodeBase64url(credential.response.clientDataJSON),
        attestationObject: encodeBase64url(credential.response.attestationObject),
        transports: credential.response.getTransports ? credential.response.getTransports() : []
      }
    };
  }

  function authenticationToJSON(credential) {
    return {
      id: credential.id,
      rawId: encodeBase64url(credential.rawId),
      type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment,
      clientExtensionResults: credential.getClientExtensionResults(),
      response: {
        authenticatorData: encodeBase64url(credential.response.authenticatorData),
        clientDataJSON: encodeBase64url(credential.response.clientDataJSON),
        signature: encodeBase64url(credential.response.signature),
        userHandle: encodeBase64url(credential.response.userHandle)
      }
    };
  }

  async function fetchJSON(url, csrfToken, body) {
    var response = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
      body: JSON.stringify(body || {})
    });
    var payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'No pudimos completar la operación.');
    return payload;
  }

  function friendlyError(error) {
    if (error && error.name === 'NotAllowedError') {
      return 'La operación fue cancelada o el dispositivo no pudo verificar tu identidad.';
    }
    if (error && error.name === 'SecurityError') {
      return 'La biometría y las passkeys requieren un HTTPS confiable. Abrí la dirección segura que muestra iniciar_red.ps1.';
    }
    return error && error.message ? error.message : 'No pudimos completar la operación.';
  }

  function showStatus(element, message, isError) {
    if (!element) return;
    element.textContent = message;
    element.className = 'passkey-status ' + (isError ? 'passkey-status-error' : 'passkey-status-success');
    element.hidden = false;
  }

  function webAuthnAvailable() {
    return Boolean(window.isSecureContext && window.PublicKeyCredential && navigator.credentials);
  }

  async function setupRegistration() {
    var button = document.querySelector('[data-passkey-register]');
    if (!button) return;
    var status = document.getElementById('passkey-status');
    var available = webAuthnAvailable();
    if (!available) {
      var message;
      if (!window.isSecureContext && window.location.protocol !== 'https:') {
        message = 'Abriste AmpereStore con HTTP. Usá la dirección HTTPS con dominio que muestra iniciar_red.ps1.';
      } else if (!window.isSecureContext) {
        message = 'El navegador no confía en este certificado. Instalá la CA local de AmpereStore, cerrá y volvé a abrir el navegador.';
      } else {
        message = 'Este navegador no ofrece biometría, passkeys ni una llave de seguridad compatible.';
      }
      showStatus(status, message, true);
      return;
    }
    button.disabled = false;
    button.addEventListener('click', async function () {
      button.disabled = true;
      status.hidden = true;
      try {
        var csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
        var options = await fetchJSON(button.dataset.optionsUrl, csrf, {});
        var credential = await navigator.credentials.create({publicKey: creationOptionsFromJSON(options)});
        var nameInput = document.getElementById('passkey-name');
        await fetchJSON(button.dataset.verifyUrl, csrf, {
          name: nameInput ? nameInput.value : 'Este dispositivo',
          credential: registrationToJSON(credential)
        });
        window.location.reload();
      } catch (error) {
        showStatus(status, friendlyError(error), true);
        button.disabled = false;
      }
    });
  }

  async function setupLogin() {
    var button = document.querySelector('[data-passkey-login]');
    if (!button) return;
    var status = document.getElementById('passkey-login-status');
    if (!webAuthnAvailable()) return;
    button.hidden = false;
    button.addEventListener('click', async function () {
      button.disabled = true;
      status.hidden = true;
      try {
        var csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
        var nextInput = document.querySelector('[name=next]');
        var options = await fetchJSON(button.dataset.optionsUrl, csrf, {
          next: nextInput ? nextInput.value : '/'
        });
        if (options.redirect) {
          window.location.assign(options.redirect);
          return;
        }
        var credential = await navigator.credentials.get({publicKey: requestOptionsFromJSON(options)});
        var result = await fetchJSON(button.dataset.verifyUrl, csrf, {
          credential: authenticationToJSON(credential)
        });
        window.location.assign(result.redirect || '/');
      } catch (error) {
        showStatus(status, friendlyError(error), true);
        button.disabled = false;
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    setupRegistration();
    setupLogin();
  });
})();
