import json
from flask import Flask, request, jsonify
from google.cloud import secretmanager
from google.cloud import documentai
import requests
import re

app = Flask(__name__)

# --- Configuración y Carga de Secretos ---
WHATSAPP_SECRET_ID = "whatsapp-permanent-token"
VERIFY_TOKEN = "FK6xvrpVFDpR3YQCRGWRhkS5A3fVQ3hHcJo92AMXgfddDcKJL43kFRzL1EveKtJC"
DOCUMENT_AI_LOCATION = "us"
DOCUMENT_AI_PROCESSOR_ID = "623b3141ba0444ab"

def get_secret(secret_id):
    """Accede a un secreto almacenado en Google Secret Manager."""
    project_id = "supercharly"
    
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        print(f"ERROR: No se pudo acceder al secreto {secret_id}. Asegúrate de que la cuenta de servicio de Cloud Run tenga el rol 'Secret Manager Secret Accessor'. Detalle: {e}")
        return None

# Carga el token permanente al inicio del servicio
# ¡IMPORTANTE! Este token debe cargarse una vez.
WHATSAPP_ACCESS_TOKEN = get_secret(WHATSAPP_SECRET_ID)
if not WHATSAPP_ACCESS_TOKEN:
    print("FATAL: No se pudo cargar el Token de Acceso de WhatsApp. El servicio puede fallar.")


# --- Funciones de Integración (Simuladas) ---

def process_invoice_with_document_ai(image_data):
    try:
        client = documentai.DocumentProcessorServiceClient()
        name = client.processor_path("supercharly", DOCUMENT_AI_LOCATION, DOCUMENT_AI_PROCESSOR_ID)
        raw_document = documentai.RawDocument(content=image_data, mime_type="image/jpeg")
        request = documentai.ProcessRequest(name=name, raw_document=raw_document)
        result = client.process_document(request=request)
        doc = result.document
        def get_entity(type_name):
            for e in doc.entities:
                if e.type_ == type_name:
                    return e
            return None
        def text(e):
            return e.mention_text if e and e.mention_text else None
        supplier = text(get_entity("supplier_name")) or text(get_entity("vendor_name"))
        date = text(get_entity("invoice_date"))
        currency = text(get_entity("currency"))
        total_entity = get_entity("total_amount")
        amount_text = None
        if total_entity:
            for p in getattr(total_entity, "properties", []):
                if p.type_ in ("amount", "value") and not amount_text:
                    amount_text = p.mention_text
                if p.type_ == "currency" and not currency:
                    currency = p.mention_text
            if not amount_text:
                amount_text = total_entity.mention_text
        def parse_amount(s):
            if not s:
                return None
            m = re.search(r"([-+]?[0-9]*[.,][0-9]+|[-+]?[0-9]+)", s)
            return float(m.group(1).replace(",", ".")) if m else None
        amount = parse_amount(amount_text)
        extracted_data = {
            "proveedor": supplier or "",
            "fecha": date or "",
            "monto_total": amount if amount is not None else None,
            "moneda": currency or ""
        }
        return extracted_data
    except Exception:
        return {"proveedor": "", "fecha": "", "monto_total": None, "moneda": ""}


def save_to_google_sheets(data):
    """
    SIMULACIÓN: Guardar los datos estructurados en una hoja de cálculo de Google Sheets.
    
    En una implementación real, aquí usarías la librería 'google-api-python-client'.
    """
    SPREADSHEET_ID = "YOUR_SPREADSHEET_ID"
    
    # Reemplaza esta simulación con la llamada real a la API de Sheets
    # Asegúrate de que la cuenta de servicio de Cloud Run esté compartida con la hoja de Sheets.
    print(f"Intentando guardar datos en Google Sheets ({SPREADSHEET_ID}): {data}")

    # SIMULACIÓN DE ÉXITO
    return True

def download_whatsapp_media(media_id):
    """
    Descarga la imagen de la factura usando el ID y el Token Permanente.
    """
    if not WHATSAPP_ACCESS_TOKEN:
        print("ERROR: Token de WhatsApp no disponible para descargar media.")
        return None

    url = f"https://graph.facebook.com/v19.0/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}

    # Primer GET para obtener la URL de descarga real
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        media_info = response.json()
        download_url = media_info.get("url")

        if not download_url:
            print(f"ERROR: No se encontró URL de descarga en la respuesta de Meta: {media_info}")
            return None

        # Segundo GET para descargar el contenido binario del archivo
        # Se requiere el mismo token en el header para la descarga
        media_response = requests.get(download_url, headers=headers)
        media_response.raise_for_status()

        return media_response.content # Contenido binario de la imagen

    except requests.exceptions.RequestException as e:
        print(f"ERROR en la descarga de media o al obtener la URL: {e}")
        return None


# --- Ruta del Webhook Principal ---

@app.route("/", methods=["GET", "POST"])
def webhook():
    """Maneja las solicitudes GET (Verificación) y POST (Mensaje) de Meta."""
    
    # ----------------------------------------------------
    # LÓGICA GET: Verificación del Webhook de Meta
    # ----------------------------------------------------
    if request.method == "GET":
        try:
            mode = request.args.get("hub.mode")
            token = request.args.get("hub.verify_token")
            challenge = request.args.get("hub.challenge")

            if mode and token and mode == "subscribe" and token == VERIFY_TOKEN:
                print("Webhook verificado con éxito!")
                return challenge, 200
            else:
                print(f"Fallo en la verificación. Modo: {mode}, Token recibido: {token}")
                return "Verification failed. Token mismatch or parameters missing.", 403
        except Exception as e:
            print(f"Error durante la verificación GET: {e}")
            return "Internal Server Error during verification.", 500

    # ----------------------------------------------------
    # LÓGICA POST: Recepción de Mensajes de WhatsApp
    # ----------------------------------------------------
    elif request.method == "POST":
        data = request.get_json()
        print(f"Received Webhook Payload: {json.dumps(data, indent=2)}")

        # 1. Navegar el Payload para encontrar el ID del archivo
        try:
            entry = data["entry"][0]
            change = entry["changes"][0]
            
            # Verificamos si es un mensaje de WhatsApp
            if change["value"]["messaging_product"] == "whatsapp":
                message = change["value"]["messages"][0]
                message_type = message.get("type")
                
                # Verificamos si es una imagen
                if message_type == "image":
                    media_id = message["image"]["id"]
                    print(f"Mensaje de imagen recibido. Media ID: {media_id}")

                    # 2. Descargar la imagen
                    image_data = download_whatsapp_media(media_id)

                    if image_data:
                        # 3. Procesar con Document AI (Extracción de datos)
                        extracted_invoice_data = process_invoice_with_document_ai(image_data)

                        # 4. Guardar en Google Sheets
                        if extracted_invoice_data:
                            if save_to_google_sheets(extracted_invoice_data):
                                print("Factura procesada y datos guardados exitosamente en Google Sheets.")
                            else:
                                print("ERROR: Falló al guardar en Google Sheets.")
                        
                        
                        response_message = "Tu factura ha sido recibida y procesada."
                        send_whatsapp_message(message["from"], response_message)

                else:
                    print(f"Mensaje no procesado: Tipo '{message_type}' no es 'image'.")

        except Exception as e:
            # Captura cualquier error en el procesamiento (ej: estructura de payload inesperada)
            print(f"ERROR grave en el flujo de procesamiento: {e}")

        # Meta requiere una respuesta 200 OK para evitar reintentos.
        return jsonify({"status": "received"}), 200
