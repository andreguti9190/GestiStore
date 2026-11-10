# AmpereStore (GestiStore)

AmpereStore es una **tienda de tecnología y componentes** desarrollada con **Django**. Permite
gestionar un catálogo de productos, que los clientes compren a través de un carrito y que los
administradores controlen el inventario y vean el historial completo de ventas de cada usuario.

---

## 🚀 Inicio fácil para PC y celular

Hacé doble clic en:

```text
iniciar_facil.bat
```

El iniciador crea un enlace HTTPS temporal, lo copia al portapapeles y lo abre en la PC. Ese mismo
enlace se puede enviar o pegar en cualquier celular o computadora. Los demás dispositivos no tienen
que instalar certificados, descargar una app, estar en el mismo Wi-Fi ni configurar el firewall.
El enlace funciona mientras la ventana del iniciador permanezca abierta.

Este modo usa un túnel rápido gratuito de Cloudflare. En la primera ejecución, la PC que hospeda
AmpereStore prepara automáticamente las dependencias de Python dentro de `.runtime` y el componente
oficial `cloudflared`; las personas que abren el
enlace no instalan ni descargan nada. La aplicación queda accesible desde Internet
para quien tenga el enlace, pero las cuentas continúan protegidas por el inicio de sesión de
AmpereStore. El dominio temporal puede cambiar al reiniciar. El reconocimiento facial queda ligado
a la cuenta y continúa disponible aunque cambie el enlace.

También se puede iniciar desde una terminal:

```powershell
.\iniciar_facil.bat
```

> Para cerrar AmpereStore y desactivar el enlace, presioná **Ctrl + C** o cerrá la ventana.

### Modo avanzado: solamente red local

`iniciar_red.ps1` conserva el modo HTTPS local. No hace falta instalar ningún certificado: el
navegador mostrará una advertencia de certificado no reconocido y basta con elegir
**Avanzado → Continuar** para entrar. La autoridad certificadora se sigue generando como archivo
opcional (`.certificados/amperestore-ca.cer`) por si querés eliminar ese aviso, y también se puede
descargar desde `/certificado-local/`.

```powershell
powershell -ExecutionPolicy Bypass -File .\iniciar_red.ps1
```

La IP se detecta automáticamente. También se puede indicar manualmente con `-Ip`, cambiar el puerto
con `-Port` o proporcionar un dominio propio con `-Domain`.

Si solo querés ejecutarlo de forma local (sin exponerlo en la red), alcanza con:

```powershell
python manage.py runserver
```

---

## 🧰 Tecnologías

- **Python 3**
- **Django** (con SQLite como base de datos)
- **HTML / CSS** con plantillas de Django
- **Cloudflare Tunnel** para el enlace HTTPS temporal y **PowerShell** para el modo de red local
- **SMTP (Gmail)** para el envío de correos

---

## 📁 Estructura del proyecto

```
GestiStore/
├── GestiStore/            # Configuración del proyecto
│   ├── settings.py        # Ajustes (base de datos, email, static, etc.)
│   ├── urls.py            # URLs raíz (admin, login, recuperación de contraseña)
│   └── wsgi.py / asgi.py
├── Tienda/                # Aplicación principal
│   ├── models.py          # Perfil, Producto, Venta, DetalleVenta
│   ├── views.py           # Toda la lógica de las vistas
│   ├── forms.py           # Formularios (producto, registro, login)
│   ├── urls.py            # URLs de la tienda
│   ├── emails.py          # Envío de código de login y comprobantes
│   ├── admin.py           # Registro de modelos en el admin de Django
│   ├── migrations/        # Migraciones de la base de datos
│   ├── static/            # CSS, imágenes
│   └── Templates/         # Plantillas HTML
├── iniciar_red.ps1        # Script de arranque en red (PowerShell)
├── iniciar_facil.bat      # Inicio de un clic con enlace HTTPS temporal
├── manage.py
├── db.sqlite3             # Base de datos SQLite
└── .env                   # Variables de entorno (credenciales de email)
```

---

## ✨ Funcionalidades

### Autenticación y seguridad
- **Registro** de usuarios con validación de email único.
- **Verificación en dos pasos (2FA) opcional por cuenta**: se activa o desactiva desde
  **Seguridad**. Mientras está activa, el inicio de sesión pide usuario + contraseña y luego un
  **código de 6 dígitos enviado por email** (vence a los 10 minutos, máximo 5 intentos y reenvío
  limitado a 60 s). También solicita confirmar la identidad antes de comprar. Si está desactivada,
  se ingresa solamente con la contraseña y el checkout no pide una confirmación extra.
- Al crear la cuenta se puede optar por activar el doble factor desde el primer momento; si no se
  marca, la cuenta queda habilitada directamente.
- **Reconocimiento facial opcional con cámara**: funciona desde un navegador moderno en celular o
  PC, sin Face ID, huella, aplicación ni certificado instalado por el visitante. Se guardan
  descriptores numéricos del rostro y no fotos o videos.
- Las passkeys registradas con la versión anterior se conservan y pueden eliminarse desde la
  sección avanzada de Seguridad.
- **Recuperación de contraseña** por email con enlaces temporales (valen 1 hora).

### Roles de usuario
- **Operador (cliente):** navega el catálogo, agrega productos al **carrito**, realiza compras y
  consulta **Mis Compras**.
- **Administrador:** no usa carrito ni "Mis compras". En su lugar tiene el **Historial de ventas**,
  ve todas las compras de todos los usuarios, y puede **crear, editar y eliminar** productos.

### Catálogo y compras
- Catálogo con **buscador** y **filtro por categoría**.
- Detalle de producto con productos relacionados.
- Carrito de compras (guardado en sesión) y **checkout** con validación.
- Método de pago: **Mercado Pago Checkout Pro** (tarjeta, dinero en cuenta y otros medios disponibles).
- Envío a domicilio con dirección escrita y **mapa automático** según la dirección (Georef + Esri);
  si la dirección no se puede ubicar, la compra continúa sin exigir un punto manual.
- Al confirmar la compra se **descuenta el stock** de forma atómica y se genera un **código de venta**
  (`GS-XXXXXXXX`).
- Se envía un **comprobante de compra por email** al usuario.

### Panel de administración
- Historial de ventas **agrupado por usuario**, con total gastado y cantidad de compras.
- CRUD completo de productos desde la propia tienda.
- Admin de Django disponible en `/admin/`.

---

## 🗂️ Modelos

| Modelo | Descripción |
|---|---|
| **Perfil** | Extiende al `User` de Django con el rol: `admin` u `operador`. |
| **Producto** | Nombre, descripción, precio, stock, categoría, imagen, peso y estado (`activo`). |
| **Venta** | Compra de un usuario: total, método de pago, estado y código único. |
| **DetalleVenta** | Ítems de cada venta: producto, cantidad, precio unitario y subtotal. |

### Categorías de productos
Informática, Componente PC, Periféricos y Gaming, Redes y Conectividad, Celulares y Accesorios,
Cables y Adaptadores, Electrónica y Desarrollo, Seguridad y Domótica, Lectores de Tarjetas y Otros.

---

## ⚙️ Requisitos previos

- Python 3 instalado.
- Dependencias instaladas:
  ```powershell
  pip install -r requirements.txt
  ```
- Una cuenta de Gmail (o servidor SMTP) para el envío de correos.

---

## 🔧 Configuración

Para configurar Gmail con una ventana guiada, abrí `configurar_correo.bat`.
Ingresá el correo remitente y una contraseña de aplicación de Google. El asistente
comprueba la autenticación SMTP sin enviar mensajes, guarda los datos en `.env`
(ignorado por Git) y conserva las demás opciones del archivo. Luego reiniciá
`iniciar_facil.bat`. Si faltan credenciales, el iniciador mostrará un aviso.

El túnel sirve las imágenes subidas desde `media/` con `SERVE_MEDIA_FILES=true`,
manteniendo `DEBUG=False`. Este servidor de archivos es para la demo local con túnel.

Las credenciales de correo se leen desde un archivo `.env` en la raíz del proyecto (no se sube al
repositorio). Ejemplo de contenido:

```env
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=tu-correo@gmail.com
EMAIL_HOST_PASSWORD=tu-clave-de-aplicacion
DEFAULT_FROM_EMAIL=AmpereStore <tu-correo@gmail.com>

# Solamente si se mantienen passkeys en producción:
WEBAUTHN_RP_ID=amperestore.com.ar
WEBAUTHN_ORIGIN=https://amperestore.com.ar

# Umbral opcional del reconocimiento facial (menor = más estricto):
FACE_RECOGNITION_THRESHOLD=0.42
```

> Para Gmail se recomienda usar una **contraseña de aplicación**, no la contraseña normal.

---

## 🛠️ Puesta en marcha (primera vez)

```powershell
# 1. Aplicar las migraciones
python manage.py migrate

# 2. (Opcional) Crear un superusuario de Django
python manage.py createsuperuser
```

Luego iniciar el servidor con el script de red (ver más arriba) o con `python manage.py runserver`.

### Probar Mercado Pago Checkout Pro

Con `MERCADOPAGO_MODE=test`, la preferencia usa el sandbox y no procesa dinero real. Para completar una compra de prueba, abrí el checkout en una sesión privada, elegí **Ingresar con mi cuenta** y usá una cuenta de prueba de tipo **Comprador** de la misma aplicación. No uses la cuenta personal del vendedor ni el flujo invitado con un correo real, porque Mercado Pago puede finalizarlo con su pantalla genérica de error.

La cuenta compradora y su código de verificación se consultan en Mercado Pago Developers, dentro de **Integraciones > aplicación > Cuentas de prueba**. Para pagos reales hay que usar credenciales productivas y `MERCADOPAGO_MODE=production`.

---

## Despliegue en Vercel

La versión de producción usa **Django ASGI**, **PostgreSQL (Neon)** y un
**Vercel Blob público** para que cuentas, sesiones, ventas e imágenes persistan
aunque las Functions se reinicien. SQLite y `media/` siguen disponibles para
`iniciar_facil.bat`, pero no se usan en Vercel.

### 1. Preparar los servicios

1. Subí el repositorio a GitHub e importalo como proyecto en Vercel.
2. En **Storage**, conectá una base PostgreSQL de Neon y un Blob Store público.
   Las integraciones deben exponer `DATABASE_URL` y `BLOB_STORE_ID`.
3. Configurá estas variables para Production y Preview:

```env
DJANGO_SECRET_KEY=una-clave-larga-y-aleatoria
DJANGO_DEBUG=false
PUBLIC_BASE_URL=https://tu-dominio.vercel.app
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=tu-correo@gmail.com
EMAIL_HOST_PASSWORD=tu-clave-de-aplicacion
DEFAULT_FROM_EMAIL=AmpereStore <tu-correo@gmail.com>
EMAIL_NOTICES_BACKGROUND=false
OPENAI_API_KEY=una-clave-nueva
OPENAI_CHAT_MODEL=gpt-6-luna
MERCADOPAGO_ACCESS_TOKEN=tu-token
MERCADOPAGO_PUBLIC_KEY=tu-clave-publica
MERCADOPAGO_WEBHOOK_SECRET=tu-secreto-webhook
MERCADOPAGO_MODE=production
WEBAUTHN_RP_ID=tu-dominio.vercel.app
WEBAUTHN_ORIGIN=https://tu-dominio.vercel.app
```

Vercel agrega sus propios dominios a los hosts permitidos. Para un dominio
propio, agregá además `DJANGO_ALLOWED_HOSTS` y
`DJANGO_CSRF_TRUSTED_ORIGINS=https://tu-dominio`.

> Nunca subas `.env`, `.env.vercel`, el volcado de datos ni claves al repositorio.
> Si una clave fue compartida por chat o captura, revocala y generá otra antes
> de cargarla en Vercel.

### 2. Crear el esquema y trasladar los datos actuales

Instalá la CLI (`npm install -g vercel`), iniciá sesión y vinculá el proyecto con
`vercel link`. Luego, desde PowerShell:

```powershell
# Exportar la base SQLite local (el archivo queda ignorado por Git)
& "C:\Users\Gustavo Estevez\AppData\Local\Programs\Python\Python313\python.exe" manage.py dumpdata --natural-foreign --natural-primary --exclude contenttypes --exclude auth.permission --exclude sessions --exclude admin.logentry --indent 2 --output deployment-data.json

# Descargar las variables del entorno de producción sin reemplazar el .env local
vercel env pull .env.vercel --environment=production
$env:GESTISTORE_ENV_FILE = '.env.vercel'

# Crear tablas, importar registros y subir las imágenes locales a Blob
& "C:\Users\Gustavo Estevez\AppData\Local\Programs\Python\Python313\python.exe" manage.py migrate
& "C:\Users\Gustavo Estevez\AppData\Local\Programs\Python\Python313\python.exe" manage.py loaddata deployment-data.json
& "C:\Users\Gustavo Estevez\AppData\Local\Programs\Python\Python313\python.exe" manage.py migrar_imagenes_blob

Remove-Item Env:GESTISTORE_ENV_FILE
```

Para la carga ejecutada desde la PC, `.env.vercel` debe incluir un
`BLOB_READ_WRITE_TOKEN`; se genera desde el Blob Store y no se versiona. En las
Functions desplegadas, el SDK usa automáticamente la identidad OIDC de Vercel
junto con `BLOB_STORE_ID`.

Después hacé un nuevo deploy. Verificá registro, login y 2FA, recuperación de
contraseña, creación de producto con imagen, una compra de prueba, el webhook de
Mercado Pago y el chatbot. El panel vendedor usa WebSocket y además consulta una
revisión cada 15 segundos, por lo que se actualiza incluso si Vercel atiende cada
conexión desde una instancia diferente.

## 🧪 Tests

```powershell
python manage.py test Tienda
```

---

## 🔗 Rutas principales

| Ruta | Descripción | Acceso |
|---|---|---|
| `/` | Inicio | Autenticado |
| `/login/` | Inicio de sesión | Público |
| `/registro/` | Registro de usuario | Público |
| `/cuenta/seguridad/` | Activar o desactivar 2FA, y gestionar el reconocimiento facial | Autenticado |
| `/productos/` | Catálogo de productos | Autenticado |
| `/carrito/` | Carrito de compras | Operador |
| `/mis-compras/` | Historial de compras propias | Operador |
| `/ventas/` | Historial de todas las ventas | Admin |
| `/admin/` | Panel de administración de Django | Admin |

---

## 📌 Nota

El modo local conserva `DEBUG=True`. El despliegue documentado usa `DEBUG=False`,
PostgreSQL y almacenamiento persistente. El reconocimiento facial sigue siendo
una función demostrativa: antes de un uso comercial corresponde sumar controles
de prueba de vida, una revisión legal y protección específica para datos biométricos.

Los navegadores solamente permiten abrir la cámara desde **HTTPS confiable** o `localhost`.
`iniciar_facil.bat` crea el enlace HTTPS temporal que debe compartirse con los demás dispositivos;
no hace falta instalar nada en ellos. `iniciar_red.ps1` queda como alternativa técnica para una red
local y requiere confiar manualmente su certificado en cada equipo.
