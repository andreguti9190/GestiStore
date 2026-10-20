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
AmpereStore prepara automáticamente el componente oficial `cloudflared`; las personas que abren el
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

`iniciar_red.ps1` conserva el modo HTTPS local. Este modo requiere instalar la autoridad
certificadora en cada dispositivo y está pensado para pruebas sin publicar la aplicación en
Internet.

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
- **Inicio de sesión en dos pasos (2FA)**: primero usuario + contraseña y luego un **código de 6
  dígitos enviado por email** (vence a los 10 minutos, máximo 5 intentos y reenvío limitado a 60 s).
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
- Métodos de pago: tarjeta de crédito, débito y transferencia.
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

---

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
| `/cuenta/seguridad/` | Registrar, actualizar o eliminar reconocimiento facial | Autenticado |
| `/productos/` | Catálogo de productos | Autenticado |
| `/carrito/` | Carrito de compras | Operador |
| `/mis-compras/` | Historial de compras propias | Operador |
| `/ventas/` | Historial de todas las ventas | Admin |
| `/admin/` | Panel de administración de Django | Admin |

---

## 📌 Nota

El proyecto es una **demo**, por lo que `DEBUG` está en `True`. Para producción habría que configurar
variables de entorno, un servidor SMTP propio, almacenamiento cifrado adecuado para la plantilla
biométrica, controles de prueba de vida y una base de datos más robusta.

Los navegadores solamente permiten abrir la cámara desde **HTTPS confiable** o `localhost`.
`iniciar_facil.bat` crea el enlace HTTPS temporal que debe compartirse con los demás dispositivos;
no hace falta instalar nada en ellos. `iniciar_red.ps1` queda como alternativa técnica para una red
local y requiere confiar manualmente su certificado en cada equipo.
