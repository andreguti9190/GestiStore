(function () {
  'use strict';

  var script = document.currentScript;
  var modelUrl = script && script.dataset.modelUrl;
  var modal = document.querySelector('[data-face-modal]');
  var video = modal && modal.querySelector('[data-face-video]');
  var modalStatus = modal && modal.querySelector('[data-face-modal-status]');
  var progress = modal && modal.querySelector('[data-face-progress]');
  var placeholder = modal && modal.querySelector('[data-face-placeholder]');
  var pageStatus = document.getElementById('face-page-status');
  var loginButton = document.querySelector('[data-face-login]');
  var enrollButton = document.querySelector('[data-face-enroll]');
  var purchaseButton = document.querySelector('[data-face-purchase]');
  var stream = null;
  var cancelled = false;
  var modelsPromise = null;
  var enginePromise = null;
  var busy = false;

  if (!modal || (!loginButton && !enrollButton && !purchaseButton)) return;

  function csrfToken() {
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function sleep(milliseconds) {
    return new Promise(function (resolve) { window.setTimeout(resolve, milliseconds); });
  }

  function showPageStatus(message, isError) {
    if (!pageStatus) return;
    pageStatus.textContent = message;
    pageStatus.className = 'face-page-status ' + (isError ? 'face-status-error' : 'face-status-success');
    pageStatus.hidden = false;
  }

  function setModalStatus(message) {
    if (modalStatus) modalStatus.textContent = message;
  }

  function stopCamera() {
    if (stream) {
      stream.getTracks().forEach(function (track) { track.stop(); });
      stream = null;
    }
    if (video) video.srcObject = null;
  }

  function closeModal() {
    cancelled = true;
    stopCamera();
    modal.hidden = true;
    document.body.classList.remove('face-modal-open');
  }

  function openModal() {
    cancelled = false;
    modal.hidden = false;
    document.body.classList.add('face-modal-open');
    if (progress) progress.style.width = '0%';
    if (placeholder) placeholder.hidden = false;
    setModalStatus('Esperando permiso para usar la cámara…');
  }

  function cameraErrorMessage(error) {
    if (!window.isSecureContext) {
      return 'La cámara requiere HTTPS. Abrí AmpereStore con el enlace de iniciar_facil.bat.';
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      return 'Este navegador no permite usar la cámara. Probá con Chrome, Edge, Firefox o Safari actualizado.';
    }
    if (error && error.name === 'NotFoundError') {
      return 'No encontramos una cámara disponible en este dispositivo.';
    }
    if (error && (error.name === 'NotAllowedError' || error.name === 'SecurityError')) {
      return 'No tenemos permiso para usar la cámara. Habilitala desde el candado del navegador y volvé a intentar.';
    }
    if (error && (error.name === 'NotReadableError' || error.name === 'AbortError')) {
      return 'La cámara está ocupada o no pudo abrirse. Cerrá otras aplicaciones que la estén usando.';
    }
    return (error && error.message) || 'No pudimos iniciar el reconocimiento facial.';
  }

  function loadModels() {
    if (modelsPromise) return modelsPromise;
    modelsPromise = new Promise(function (resolve, reject) {
      if (!window.faceapi || !modelUrl) {
        reject(new Error('El reconocimiento facial no pudo cargarse. Reiniciá AmpereStore e intentá de nuevo.'));
        return;
      }

      async function loadWithRetry(net, label, step) {
        if (net.isLoaded) return;
        var lastError;
        for (var attempt = 1; attempt <= 3; attempt += 1) {
          try {
            setModalStatus('Preparando ' + label + ' (' + step + '/3)…');
            await net.loadFromUri(modelUrl);
            return;
          } catch (error) {
            lastError = error;
            if (attempt < 3) {
              setModalStatus('La conexión se interrumpió. Reintentando ' + label + '…');
              await sleep(700 * attempt);
            }
          }
        }
        throw lastError;
      }

      (async function () {
        if (!enginePromise) {
          enginePromise = (async function () {
            setModalStatus('Inicializando el análisis facial…');
            try {
              var webglReady = await faceapi.tf.setBackend('webgl');
              if (!webglReady) throw new Error('WebGL no disponible');
              await faceapi.tf.ready();
            } catch (webglError) {
              window.console.warn('WebGL no está disponible; se usará CPU:', webglError);
              var cpuReady = await faceapi.tf.setBackend('cpu');
              if (!cpuReady) throw webglError;
              await faceapi.tf.ready();
            }
          })().catch(function (error) {
            enginePromise = null;
            throw error;
          });
        }
        await enginePromise;

        // La carga secuencial es más estable a través del enlace temporal que
        // seis descargas simultáneas de manifiestos y pesos.
        await loadWithRetry(faceapi.nets.tinyFaceDetector, 'el detector', 1);
        await loadWithRetry(faceapi.nets.faceLandmark68Net, 'los puntos faciales', 2);
        await loadWithRetry(faceapi.nets.faceRecognitionNet, 'el reconocimiento', 3);
      })().then(resolve).catch(function (error) {
        window.console.error('No se pudieron cargar los modelos faciales:', error);
        modelsPromise = null;
        reject(new Error('No pudimos preparar el reconocimiento facial. Esperá unos segundos e intentá nuevamente.'));
      });
    });
    return modelsPromise;
  }

  async function startCamera() {
    if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error(cameraErrorMessage());
    }
    stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: 'user',
        width: { ideal: 640 },
        height: { ideal: 480 }
      }
    });
    video.srcObject = stream;
    await video.play();
    var deadline = Date.now() + 10000;
    while (
      (video.readyState < 2 || video.videoWidth < 64 || video.videoHeight < 64)
      && Date.now() < deadline
    ) {
      if (cancelled) throw new Error('Operación cancelada.');
      await sleep(100);
    }
    if (video.readyState < 2 || video.videoWidth < 64 || video.videoHeight < 64) {
      throw new Error('La cámara se abrió, pero no entregó una imagen. Cerrá otras aplicaciones y volvé a intentar.');
    }
    if (placeholder) placeholder.hidden = true;
  }

  async function captureDescriptors() {
    var descriptors = [];
    var attempts = 0;
    var frame = document.createElement('canvas');
    frame.width = video.videoWidth;
    frame.height = video.videoHeight;
    var frameContext = frame.getContext('2d', { willReadFrequently: true });
    if (!frameContext) throw new Error('El navegador no pudo preparar la imagen de la cámara.');
    var detectorOptions = new faceapi.TinyFaceDetectorOptions({
      inputSize: 416,
      scoreThreshold: 0.45
    });

    while (descriptors.length < 3 && attempts < 45) {
      if (cancelled) throw new Error('Operación cancelada.');
      attempts += 1;
      frameContext.drawImage(video, 0, 0, frame.width, frame.height);
      var detections = await faceapi
        .detectAllFaces(frame, detectorOptions)
        .withFaceLandmarks()
        .withFaceDescriptors();

      if (detections.length === 0) {
        setModalStatus('No vemos tu rostro. Acercate un poco y mirá al frente.');
      } else if (detections.length > 1) {
        setModalStatus('Debe aparecer una sola persona frente a la cámara.');
      } else {
        var box = detections[0].detection.box;
        var frameArea = Math.max(1, video.videoWidth * video.videoHeight);
        var faceArea = box.width * box.height;
        if (faceArea / frameArea < 0.08) {
          setModalStatus('Acercate un poco más a la cámara.');
        } else {
          descriptors.push(Array.from(detections[0].descriptor));
          if (progress) progress.style.width = Math.round(descriptors.length / 3 * 100) + '%';
          setModalStatus(
            descriptors.length < 3
              ? 'Perfecto. Mantené la mirada un momento más…'
              : 'Listo. Verificando tu rostro…'
          );
          await sleep(450);
        }
      }
      await sleep(220);
    }

    if (descriptors.length < 3) {
      throw new Error('No pudimos obtener una imagen clara. Mejorá la luz y volvé a intentar.');
    }
    return descriptors;
  }

  async function postJson(url, payload) {
    var response = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken()
      },
      body: JSON.stringify(payload)
    });
    var data;
    try {
      data = await response.json();
    } catch (_error) {
      data = {};
    }
    if (!response.ok) throw new Error(data.error || 'No pudimos completar la operación.');
    return data;
  }

  async function runFaceFlow(kind, button) {
    if (busy) return;
    var consent = document.getElementById('face-consent');
    var username = document.getElementById('login-username');
    if (kind === 'enroll' && (!consent || !consent.checked)) {
      showPageStatus('Marcá la casilla de consentimiento antes de registrar tu rostro.', true);
      if (consent) consent.focus();
      return;
    }
    if (kind === 'login' && (!username || !username.value.trim())) {
      showPageStatus('Primero escribí tu usuario.', true);
      if (username) username.focus();
      return;
    }

    busy = true;
    button.disabled = true;
    openModal();
    try {
      var modelLoading = loadModels();
      await startCamera();
      setModalStatus('Preparando el reconocimiento facial…');
      await modelLoading;
      setModalStatus('Mirá al frente y mantené el dispositivo quieto.');
      var descriptors = await captureDescriptors();
      stopCamera();

      var payload = { descriptors: descriptors };
      if (kind === 'enroll') payload.consent = true;
      if (kind === 'login') {
        payload.username = username.value.trim();
        var nextInput = document.querySelector('input[name="next"]');
        payload.next = nextInput ? nextInput.value : '/';
      }
      var result = await postJson(button.dataset.url, payload);
      closeModal();
      if (kind === 'login') {
        window.location.assign(result.redirect || '/');
      } else if (kind === 'purchase') {
        var faceMethod = document.querySelector('input[name="verification_method"][value="face"]');
        if (faceMethod) {
          faceMethod.checked = true;
          faceMethod.dispatchEvent(new Event('change', { bubbles: true }));
        }
        showPageStatus(result.message || 'Rostro confirmado. Ahora podés confirmar la compra.', false);
      } else {
        showPageStatus(result.message || 'Tu rostro quedó registrado.', false);
        window.setTimeout(function () { window.location.reload(); }, 900);
      }
    } catch (error) {
      closeModal();
      if (error && error.message !== 'Operación cancelada.') {
        showPageStatus(cameraErrorMessage(error), true);
      }
    } finally {
      busy = false;
      button.disabled = false;
    }
  }

  modal.querySelectorAll('[data-face-cancel]').forEach(function (element) {
    element.addEventListener('click', closeModal);
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !modal.hidden) closeModal();
  });

  if (loginButton) {
    loginButton.hidden = false;
    var help = document.querySelector('[data-face-help]');
    if (help) help.hidden = false;
    loginButton.addEventListener('click', function () { runFaceFlow('login', loginButton); });
  }
  if (enrollButton) {
    enrollButton.hidden = false;
    enrollButton.addEventListener('click', function () { runFaceFlow('enroll', enrollButton); });
  }
  if (purchaseButton) {
    purchaseButton.hidden = false;
    purchaseButton.addEventListener('click', function () {
      runFaceFlow('purchase', purchaseButton);
    });
  }
})();
