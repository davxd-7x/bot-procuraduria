import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import os
from datetime import datetime
import asyncio
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import io
from dotenv import load_dotenv

# Cargar variables de .env
load_dotenv()

# Servidor web para Fly.io
from aiohttp import web
import asyncio

async def handle_health(request):
    """Health check endpoint"""
    return web.Response(text="Bot OK")

async def run_web_server():
    """Ejecutar servidor web en puerto 8080"""
    app = web.Application()
    app.router.add_get('/', handle_health)
    app.router.add_get('/health', handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f'🌐 Servidor web iniciado en puerto {port}')

# ==================== CONFIGURACIÓN ====================
SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'credentials.json'
DRIVE_FOLDER_ID = '1fND6FHVGPNFFkJTcWBBeYzN5a4WGI1ZZ'  # Cambiar por el ID de tu carpeta
CANAL_PQRS_ID = 1446524564006768751 # Cambiar por el ID del canal de PQRS
ROL_PROCURADURIA_ID = 1220833789308174467  # Cambiar por el ID del rol de Procuraduria
REGISTROS_CHANNEL_ID = 1446522781897330699  # Cambiar por el ID del canal de registros
# Rol adicional autorizado a responder PQRS (poner el ID aquí o definir RESPONDER_ROLE_ID en .env)
# Si lo dejas en 0 o None, solo el rol de Procuraduría podrá responder.
RESPONDER_ROLE_ID = 1289418666353623090

# ==================== INICIALIZACIÓN ====================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Conexión a Google Drive
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=credentials)

# ==================== BASE DE DATOS ====================
def init_db():
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    
    # Tabla de documentos
    c.execute('''CREATE TABLE IF NOT EXISTS documentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT NOT NULL,
        numero TEXT NOT NULL,
        anio INTEGER NOT NULL,
        titulo TEXT,
        descripcion TEXT,
        link_drive TEXT,
        ius TEXT UNIQUE,
        attached_iuc TEXT,
        fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        registrado_por TEXT
    )''')
    
    # Tabla de PQRS
    c.execute('''CREATE TABLE IF NOT EXISTS pqrs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        radicado TEXT UNIQUE NOT NULL,
        tipo TEXT NOT NULL,
        usuario_id TEXT NOT NULL,
        usuario_nombre TEXT NOT NULL,
        asunto TEXT NOT NULL,
        descripcion TEXT NOT NULL,
        estado TEXT DEFAULT 'PENDIENTE',
        fecha_radicacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        fecha_respuesta TIMESTAMP,
        respuesta TEXT,
        canal_mensaje_id TEXT
    )''')
    
    # Tabla de casos (IUC)
    c.execute('''CREATE TABLE IF NOT EXISTS casos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        iuc TEXT UNIQUE NOT NULL,
        tipo TEXT NOT NULL,
        anio INTEGER NOT NULL,
        implicado TEXT,
        estado TEXT DEFAULT 'EN TRAMITE',
        descripcion TEXT,
        visibilidad TEXT DEFAULT 'PUBLICO',
        fecha_apertura TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        fecha_cierre TIMESTAMP,
        mensaje_id TEXT,
        canal_registros_id TEXT
    )''')
    
    conn.commit()
    conn.close()

    # Asegurar columnas nuevas en tablas existentes (si la DB ya existía)
    try:
        conn = sqlite3.connect('procuraduria.db')
        c = conn.cursor()
        # adicionar columnas si no existen
        try:
            c.execute("ALTER TABLE documentos ADD COLUMN ius TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE documentos ADD COLUMN attached_iuc TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE casos ADD COLUMN visibilidad TEXT DEFAULT 'PUBLICO'")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE casos ADD COLUMN fecha_cierre TIMESTAMP")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE casos ADD COLUMN mensaje_id TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE casos ADD COLUMN canal_registros_id TEXT")
        except sqlite3.OperationalError:
            pass
        conn.commit()
    finally:
        conn.close()

# ==================== FUNCIONES DE GOOGLE DRIVE ====================
def subir_a_drive(archivo_path, nombre_archivo):
    """Sube un archivo a Google Drive y retorna el link"""
    try:
        file_metadata = {
            'name': nombre_archivo,
            'parents': [DRIVE_FOLDER_ID]
        }
        media = MediaFileUpload(archivo_path, resumable=True)
        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        # Hacer el archivo público
        drive_service.permissions().create(
            fileId=file['id'],
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
        
        return file.get('webViewLink')
    except Exception as e:
        print(f"Error subiendo archivo: {e}")
        return None


def _parse_iuc_numeric(iuc: str) -> str:
    """Extrae la parte numérica final del IUC y la deja en 4 dígitos.
    Ej: IUC-E-2025-1 -> '0001'"""
    try:
        parts = iuc.split('-')
        last = parts[-1]
        num = int(last)
        return f"{num:04d}"
    except Exception:
        return "0000"


def generar_ius(iuc: str, tipo: str = 'F') -> str:
    """Genera un IUS único siguiendo el formato:
    IUS-(F|A)-(AÑO XXXX)-(XXXX del radicado IUC)-(X extra incremental)
    Se usa la parte numérica del IUC (4 dígitos) y se añade un contador incremental
    para evitar colisiones.
    """
    tipo = tipo.upper() if tipo and tipo.upper() in ('F', 'A') else 'F'
    # extraer año del IUC si es posible
    year = datetime.now().year
    try:
        parts = iuc.split('-')
        for p in parts:
            if p.isdigit() and len(p) == 4:
                year = int(p)
                break
    except Exception:
        pass

    iuc_num = _parse_iuc_numeric(iuc)

    # contar cuántos IUS ya existen con mismo prefijo para asignar siguiente número
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    base_prefix = f"IUS-{tipo}-{year}-{iuc_num}-"
    c.execute("SELECT COUNT(*) FROM documentos WHERE ius LIKE ?", (base_prefix + '%',))
    count = c.fetchone()[0] or 0
    next_index = count + 1
    ius = f"{base_prefix}{next_index}"
    conn.close()
    return ius

# ==================== EVENTOS DEL BOT ====================
@bot.event
async def on_ready():
    print(f'✅ Bot conectado como {bot.user}')
    init_db()
    try:
        # Si se proporciona GUILD_ID en .env, sincronizamos en ese guild
        GUILD_ID = os.getenv('GUILD_ID')
        if GUILD_ID:
            guild_obj = discord.Object(id=int(GUILD_ID))
            synced = await bot.tree.sync(guild=guild_obj)
            print(f'✅ {len(synced)} comandos sincronizados (guild {GUILD_ID})')
        else:
            synced = await bot.tree.sync()
            print(f'✅ {len(synced)} comandos sincronizados (global)')
    except Exception as e:
        print(f'❌ Error sincronizando comandos: {e}')
    # Iniciar servidor web para Fly.io
    asyncio.create_task(run_web_server())

# ==================== COMANDOS PARA CIUDADANOS ====================
@bot.tree.command(name="buscar-caso", description="Buscar un caso por IUC (solo ciudadanos)")
@app_commands.describe(iuc="Número de IUC (ej: IUC-E-2025-0001)")
async def buscar_caso(interaction: discord.Interaction, iuc: str):
    await interaction.response.defer(ephemeral=True)
    
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    c.execute("SELECT iuc, tipo, estado, visibilidad FROM casos WHERE iuc = ?", (iuc.upper(),))
    caso = c.fetchone()
    conn.close()

    if not caso:
        await interaction.followup.send("❌ Caso no encontrado", ephemeral=True)
        return

    iuc_val, tipo_val, estado_val, visibilidad_val = caso[0], caso[1], caso[2], (caso[3] if len(caso) > 3 else 'PUBLICO')

    # Si el caso es reservado y el usuario no es procuraduría, negar acceso a documentos
    rol = interaction.guild.get_role(ROL_PROCURADURIA_ID)
    es_procuraduria_user = rol in interaction.user.roles if rol else False
    if visibilidad_val and visibilidad_val.upper() == 'RESERVADO' and not es_procuraduria_user:
        await interaction.followup.send("🔒 El proceso es RESERVADO. No se puede brindar ningún documento hasta su finalización.", ephemeral=True)
        return

    # mostrar también documentos adjuntos
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    c.execute("SELECT tipo, numero, anio, titulo, ius FROM documentos WHERE attached_iuc = ?", (iuc.upper(),))
    attached_docs = c.fetchall()
    conn.close()

    msg = f"**Caso {iuc_val}**\\nTipo: {tipo_val}\\nEstado: {estado_val}"
    if attached_docs:
        msg += "\\n\\nDocumentos adjuntos:\\n" + "\\n".join([f"- {d[0]} {d[1]} de {d[2]} | IUS: {d[4]}" for d in attached_docs])
    await interaction.followup.send(msg, ephemeral=True)

@bot.tree.command(name="radicar-pqrs", description="Radicar una Petición, Queja, Reclamo o Solicitud")
async def radicar_pqrs(interaction: discord.Interaction):
    """Inicia el proceso de radicación de PQRS mediante formulario modal"""
    
    class PQRSModal(discord.ui.Modal, title='Radicar PQRS'):
        tipo_select = discord.ui.TextInput(
            label='Tipo (P/Q/R/S)',
            placeholder='P para Petición, Q para Queja, R para Reclamo, S para Solicitud',
            required=True,
            max_length=1
        )
        
        asunto = discord.ui.TextInput(
            label='Asunto',
            placeholder='Resumen breve del asunto',
            required=True,
            max_length=200
        )
        
        descripcion = discord.ui.TextInput(
            label='Descripción',
            style=discord.TextStyle.paragraph,
            placeholder='Describa detalladamente su PQRS',
            required=True,
            max_length=2000
        )
        
        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            
            # Validar tipo
            tipo_dict = {'P': 'PETICIÓN', 'Q': 'QUEJA', 'R': 'RECLAMO', 'S': 'SOLICITUD'}
            tipo_letra = self.tipo_select.value.upper()
            
            if tipo_letra not in tipo_dict:
                await interaction.followup.send(
                    "❌ Tipo inválido. Use P, Q, R o S",
                    ephemeral=True
                )
                return
            
            tipo_completo = tipo_dict[tipo_letra]
            
            # Generar radicado
            conn = sqlite3.connect('procuraduria.db')
            c = conn.cursor()
            anio = datetime.now().year
            c.execute("SELECT COUNT(*) FROM pqrs WHERE radicado LIKE ?", (f"PQRS-{anio}-%",))
            count = c.fetchone()[0] + 1
            radicado = f"PQRS-{anio}-{count:04d}"
            
            # Guardar PQRS
            try:
                c.execute("""INSERT INTO pqrs 
                    (radicado, tipo, usuario_id, usuario_nombre, asunto, descripcion) 
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (radicado, tipo_completo, str(interaction.user.id), 
                     interaction.user.name, self.asunto.value, self.descripcion.value))
                conn.commit()
                
                # Enviar al canal de PQRS
                canal = bot.get_channel(CANAL_PQRS_ID)
                if canal:
                    rol = interaction.guild.get_role(ROL_PROCURADURIA_ID)
                    embed = discord.Embed(
                        title=f"📨 Nueva PQRS: {radicado}",
                        color=discord.Color.orange(),
                        timestamp=datetime.now()
                    )
                    embed.add_field(name="Tipo", value=tipo_completo, inline=True)
                    embed.add_field(name="Radicado", value=radicado, inline=True)
                    embed.add_field(name="Usuario", value=interaction.user.mention, inline=True)
                    embed.add_field(name="Asunto", value=self.asunto.value, inline=False)
                    embed.add_field(name="Descripción", value=self.descripcion.value[:1000], inline=False)
                    
                    mensaje = await canal.send(
                        content=f"{rol.mention if rol else '@Procuraduría'}",
                        embed=embed
                    )
                    
                    # Guardar ID del mensaje
                    c.execute("UPDATE pqrs SET canal_mensaje_id = ? WHERE radicado = ?",
                             (str(mensaje.id), radicado))
                    conn.commit()
                
                conn.close()
                
                # Confirmar al usuario
                await interaction.followup.send(
                    f"✅ **PQRS radicada exitosamente**\n\n"
                    f"**Radicado:** {radicado}\n"
                    f"**Tipo:** {tipo_completo}\n\n"
                    f"Guarde su número de radicado para consultar el estado usando `/consultar-radicado`",
                    ephemeral=True
                )
                
            except Exception as e:
                conn.close()
                await interaction.followup.send(
                    f"❌ Error al radicar PQRS: {e}",
                    ephemeral=True
                )
    
    await interaction.response.send_modal(PQRSModal())

@bot.tree.command(name="consultar-radicado", description="Consultar estado de una PQRS")
@app_commands.describe(radicado="Número de radicado (ej: PQRS-2025-0001)")
async def consultar_radicado(interaction: discord.Interaction, radicado: str):
    await interaction.response.defer(ephemeral=True)
    
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    c.execute("SELECT * FROM pqrs WHERE radicado = ? AND usuario_id = ?", 
              (radicado.upper(), str(interaction.user.id)))
    pqrs = c.fetchone()
    conn.close()
    
    if not pqrs:
        await interaction.followup.send(
            f"❌ No se encontró el radicado {radicado} o no le pertenece",
            ephemeral=True
        )
        return
    
    embed = discord.Embed(
        title=f"📋 PQRS {pqrs[1]}",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    embed.add_field(name="Tipo", value=pqrs[2], inline=True)
    embed.add_field(name="Estado", value=pqrs[8], inline=True)
    embed.add_field(name="Fecha Radicación", value=pqrs[7][:10], inline=True)
    embed.add_field(name="Asunto", value=pqrs[5], inline=False)
    
    if pqrs[8] == 'RESPONDIDA' and pqrs[10]:
        embed.add_field(name="Respuesta", value=pqrs[10], inline=False)
        embed.add_field(name="Fecha Respuesta", value=pqrs[9][:10] if pqrs[9] else "N/A", inline=True)
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# ==================== COMANDOS PARA PROCURADURÍA ====================
def es_procuraduria():
    """Decorador para verificar si el usuario tiene el rol de Procuraduría"""
    async def predicate(interaction: discord.Interaction) -> bool:
        rol = interaction.guild.get_role(ROL_PROCURADURIA_ID)
        if rol in interaction.user.roles:
            return True
        await interaction.response.send_message(
            "❌ No tienes permisos para usar este comando",
            ephemeral=True
        )
        return False
    return app_commands.check(predicate)

@bot.tree.command(name="registrar-documento", description="[PROCURADURÍA] Registrar resolución o decreto")
@app_commands.describe(
    tipo="Tipo de documento",
    numero="Número del documento",
    anio="Año",
    titulo="Título del documento",
    link="Link de Google Drive",
    adjuntar_iuc="Radicado IUC al que adjuntar (opcional, ej: IUC-E-2025-0001)",
    ius_tipo="Tipo de IUS: F=Fallos, A=Autos (opcional, por defecto F)"
)
@es_procuraduria()
async def registrar_documento(
    interaction: discord.Interaction,
    tipo: str,
    numero: str,
    anio: int,
    titulo: str,
    link: str,
    adjuntar_iuc: str = None,
    ius_tipo: str = 'F'
):
    await interaction.response.defer(ephemeral=True)
    
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    
    # si se adjunta a un IUC, validar que el caso existe y que no esté archivado
    ius_value = None
    attached = None
    if adjuntar_iuc:
        attached = adjuntar_iuc.strip().upper()
        c.execute("SELECT estado, visibilidad FROM casos WHERE iuc = ?", (attached,))
        row = c.fetchone()
        if not row:
            await interaction.followup.send(f"❌ No existe el caso {attached}", ephemeral=True)
            conn.close()
            return
        estado_caso = row[0] if row and len(row) > 0 else None
        if estado_caso and estado_caso.upper() == 'ARCHIVADO':
            await interaction.followup.send(f"❌ No puede adjuntarse documentos a un caso archivado ({attached})", ephemeral=True)
            conn.close()
            return
        ius_value = generar_ius(attached, tipo=ius_tipo)
    
    try:
        c.execute("""INSERT INTO documentos 
            (tipo, numero, anio, titulo, link_drive, ius, attached_iuc, registrado_por) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (tipo.upper(), numero, anio, titulo, link, ius_value, attached, interaction.user.name))
        conn.commit()
        
        # Actualizar el mensaje del caso si está adjunto a un IUC
        if attached:
            try:
                c.execute("SELECT mensaje_id, canal_registros_id FROM casos WHERE iuc = ?", (attached,))
                caso_info = c.fetchone()
                if caso_info and caso_info[0] and caso_info[1]:
                    mensaje_id = int(caso_info[0])
                    canal_id = int(caso_info[1])
                    # Obtener el canal y el mensaje
                    try:
                        channel = bot.get_channel(canal_id) or await bot.fetch_channel(canal_id)
                        mensaje = await channel.fetch_message(mensaje_id)
                        
                        # Obtener todos los documentos adjuntos a este caso
                        c.execute("SELECT tipo, numero, anio, titulo, link_drive, ius FROM documentos WHERE attached_iuc = ? ORDER BY fecha_registro", (attached,))
                        docs = c.fetchall()
                        
                        # Construir lista de adjuntos
                        adjuntos_text = ""
                        if docs:
                            adjuntos_text = "\n".join([f"{i+1}. {d[0]} {d[1]} ({d[2]}) - {d[3]}\n   IUS: {d[5]}\n   Link: {d[4]}" for i, d in enumerate(docs)])
                        else:
                            adjuntos_text = "Ninguno"
                        
                        # Actualizar el embed del mensaje
                        embeds = mensaje.embeds
                        if embeds:
                            embed = embeds[0]
                            # Buscar y actualizar el field de "Adjuntos"
                            found = False
                            for i, field in enumerate(embed.fields):
                                if field.name == "Adjuntos":
                                    embed.set_field_at(i, name="Adjuntos", value=adjuntos_text, inline=False)
                                    found = True
                                    break
                            if not found:
                                embed.add_field(name="Adjuntos", value=adjuntos_text, inline=False)
                            
                            await mensaje.edit(embed=embed)
                    except Exception as e:
                        print(f"Error actualizando mensaje del caso: {e}")
            except Exception as e:
                print(f"Error en actualización de mensaje: {e}")
        
        # Enviar log al canal de registros si existe
        try:
            channel = bot.get_channel(REGISTROS_CHANNEL_ID) or await bot.fetch_channel(REGISTROS_CHANNEL_ID)
            embed = discord.Embed(title="Nuevo documento registrado", color=discord.Color.blue(), timestamp=datetime.now())
            embed.add_field(name="Documento", value=f"{tipo.upper()} {numero} de {anio}", inline=False)
            embed.add_field(name="Título", value=titulo or "-", inline=False)
            if attached:
                embed.add_field(name="Adjunto a IUC", value=attached, inline=True)
            if ius_value:
                embed.add_field(name="IUS generado", value=ius_value, inline=True)
            embed.add_field(name="Registrado por", value=interaction.user.name, inline=True)
            embed.add_field(name="Link", value=link or "-", inline=False)
            await channel.send(embed=embed)
        except Exception:
            pass
        
        await interaction.followup.send(
            f"✅ Documento registrado:\n**{tipo} {numero} de {anio}**\n{titulo}" + (f"\nRadicado IUS generado: **{ius_value}**" if ius_value else ""),
            ephemeral=True
        )
    except sqlite3.IntegrityError:
        await interaction.followup.send(
            "❌ Error: Ya existe un documento con esos datos",
            ephemeral=True
        )
    finally:
        conn.close()

@bot.tree.command(name="buscar-documento", description="[PROCURADURÍA] Buscar resolución o decreto")
@app_commands.describe(
    tipo="Tipo de documento (RESOLUCIÓN/DECRETO)",
    numero="Número del documento"
)
@es_procuraduria()
async def buscar_documento(interaction: discord.Interaction, tipo: str, numero: str):
    await interaction.response.defer(ephemeral=True)
    
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    c.execute("SELECT * FROM documentos WHERE tipo LIKE ? AND numero = ?", 
              (f"%{tipo}%", numero))
    docs = c.fetchall()
    conn.close()
    
    if not docs:
        await interaction.followup.send(
            f"❌ No se encontraron documentos del tipo '{tipo}' con número '{numero}'",
            ephemeral=True
        )
        return
    # Mostrar IUS y IUC adjunto si existen
    lines = []
    for d in docs:
        # documentos table: id,tipo,numero,anio,titulo,descripcion,link_drive, ius, attached_iuc, fecha_registro, registrado_por
        doc_id = d[0]
        doc_tipo = d[1]
        doc_numero = d[2]
        doc_anio = d[3]
        doc_titulo = d[4]
        doc_link = d[6]
        doc_ius = d[7]
        doc_attached = d[8]
        s = f"**{doc_tipo} {doc_numero} de {doc_anio}** - {doc_titulo}"
        if doc_ius:
            s += f" | IUS: {doc_ius}"
        if doc_attached:
            s += f" | Adjuntado a IUC: {doc_attached}"
        lines.append(s)

    await interaction.followup.send("\n".join(lines), ephemeral=True)
    
    for doc in docs:
        embed = discord.Embed(
            title=f"{doc[1]} {doc[2]} de {doc[3]}",
            description=doc[4] if doc[4] else "Sin título",
            color=discord.Color.green(),
            url=doc[6]
        )
        if doc[5]:
            embed.add_field(name="Descripción", value=doc[5], inline=False)
        embed.add_field(name="📎 Link", value=f"[Ver documento]({doc[6]})", inline=False)
        embed.set_footer(text=f"Registrado por {doc[8]}")
        
        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="registrar-caso", description="[PROCURADURÍA] Registrar nuevo caso (IUC)")
@app_commands.describe(
    tipo="Tipo de caso (E: Ético, D: Disciplinario)",
    implicado="Nombre del implicado",
    descripcion="Descripción breve del caso",
    visibilidad="Visibilidad del caso: PUBLICO o RESERVADO (opcional, por defecto PUBLICO)",
    consecutivo="Número consecutivo (XXXX, opcional, si no se proporciona se genera automáticamente)"
)
@es_procuraduria()
async def registrar_caso(
    interaction: discord.Interaction,
    tipo: str,
    implicado: str,
    descripcion: str = None,
    visibilidad: str = 'PUBLICO',
    consecutivo: int = None
):
    await interaction.response.defer(ephemeral=True)
    
    tipo = tipo.upper()
    if tipo not in ['E', 'D']:
        await interaction.followup.send(
            "❌ Tipo inválido. Use E (Ético) o D (Disciplinario)",
            ephemeral=True
        )
        return
    
    visibilidad = visibilidad.strip().upper()
    if visibilidad not in ['PUBLICO', 'RESERVADO']:
        visibilidad = 'PUBLICO'
    
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    
    # Generar IUC con 4 dígitos en el sufijo
    anio = datetime.now().year
    
    # Si se proporciona consecutivo, usarlo; si no, generar automáticamente
    if consecutivo is not None:
        consecutivo = max(1, min(9999, int(consecutivo)))
        iuc = f"IUC-{tipo}-{anio}-{consecutivo:04d}"
        # Verificar que no exista ya
        c.execute("SELECT id FROM casos WHERE iuc = ?", (iuc,))
        if c.fetchone():
            await interaction.followup.send(
                f"❌ El IUC {iuc} ya existe",
                ephemeral=True
            )
            conn.close()
            return
    else:
        c.execute("SELECT COUNT(*) FROM casos WHERE iuc LIKE ?", (f"IUC-{tipo}-{anio}-%",))
        count = c.fetchone()[0] + 1
        iuc = f"IUC-{tipo}-{anio}-{count:04d}"
    
    tipo_completo = "ÉTICO" if tipo == "E" else "DISCIPLINARIO"
    
    try:
        c.execute("""INSERT INTO casos 
            (iuc, tipo, anio, implicado, descripcion, visibilidad) 
            VALUES (?, ?, ?, ?, ?, ?)""",
            (iuc, tipo_completo, anio, implicado, descripcion, visibilidad))
        conn.commit()
        
        # Enviar log al canal de registros
        mensaje_guardado = None
        try:
            channel = bot.get_channel(REGISTROS_CHANNEL_ID) or await bot.fetch_channel(REGISTROS_CHANNEL_ID)
            embed = discord.Embed(title="Nuevo caso registrado", color=discord.Color.green(), timestamp=datetime.now())
            embed.add_field(name="IUC", value=iuc, inline=True)
            embed.add_field(name="Tipo", value=tipo_completo, inline=True)
            embed.add_field(name="Implicado", value=implicado or "-", inline=False)
            embed.add_field(name="Visibilidad", value=visibilidad, inline=True)
            embed.add_field(name="Registrado por", value=interaction.user.name, inline=True)
            embed.add_field(name="Adjuntos", value="Ninguno", inline=False)
            mensaje_guardado = await channel.send(embed=embed)
            # Guardar el ID del mensaje y del canal en la BD
            if mensaje_guardado:
                c.execute("UPDATE casos SET mensaje_id = ?, canal_registros_id = ? WHERE iuc = ?", 
                         (str(mensaje_guardado.id), str(channel.id), iuc))
                conn.commit()
        except Exception as e:
            print(f"Error enviando log a REGISTROS: {e}")
        
        await interaction.followup.send(
            f"✅ **Caso registrado**\n\n"
            f"**IUC:** {iuc}\n"
            f"**Tipo:** {tipo_completo}\n"
            f"**Implicado:** {implicado}\n"
            f"**Visibilidad:** {visibilidad}",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(
            f"❌ Error al registrar caso: {e}",
            ephemeral=True
        )
    finally:
        conn.close()

@bot.tree.command(name="responder-pqrs", description="[PROCURADURÍA] Responder una PQRS")
@app_commands.describe(
    radicado="Número de radicado",
    respuesta="Respuesta a la PQRS"
)
async def responder_pqrs(interaction: discord.Interaction, radicado: str, respuesta: str):
    await interaction.response.defer(ephemeral=True)
    # Permisos: permitir solo al rol adicional configurado (RESPONDER_ROLE_ID o .env)
    responder_role = None
    if interaction.guild:
        try:
            env_id = os.getenv('RESPONDER_ROLE_ID')
            if env_id:
                responder_role = interaction.guild.get_role(int(env_id))
        except Exception:
            responder_role = None
        if not responder_role and RESPONDER_ROLE_ID:
            try:
                responder_role = interaction.guild.get_role(int(RESPONDER_ROLE_ID))
            except Exception:
                responder_role = None

    # Si no hay rol configurado, denegar por seguridad
    if not responder_role:
        await interaction.followup.send(
            "❌ No hay un rol autorizado configurado para responder PQRS. Contacta al administrador.",
            ephemeral=True
        )
        return

    # Comprobar que el usuario tiene el rol autorizado
    if responder_role not in interaction.user.roles:
        await interaction.followup.send(
            "❌ No tienes permisos para responder PQRS.",
            ephemeral=True
        )
        return

    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    
    # Buscar PQRS
    c.execute("SELECT * FROM pqrs WHERE radicado = ?", (radicado.upper(),))
    pqrs = c.fetchone()
    
    if not pqrs:
        conn.close()
        await interaction.followup.send(
            f"❌ No se encontró el radicado {radicado}",
            ephemeral=True
        )
        return
    
    # Actualizar PQRS
    fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""UPDATE pqrs 
        SET estado = 'RESPONDIDA', respuesta = ?, fecha_respuesta = ? 
        WHERE radicado = ?""",
        (respuesta, fecha_actual, radicado.upper()))
    conn.commit()
    conn.close()
    
    # Notificar al usuario por DM
    try:
        usuario = await bot.fetch_user(int(pqrs[3]))
        embed = discord.Embed(
            title=f"📬 Respuesta a su PQRS {radicado}",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Asunto", value=pqrs[5], inline=False)
        embed.add_field(name="Respuesta", value=respuesta, inline=False)
        embed.set_footer(text="Procuraduría General de la Nación")
        
        await usuario.send(embed=embed)
        
        await interaction.followup.send(
            f"✅ PQRS {radicado} respondida y notificación enviada al usuario",
            ephemeral=True
        )
    except:
        await interaction.followup.send(
            f"✅ PQRS {radicado} respondida, pero no se pudo enviar DM al usuario",
            ephemeral=True
        )

@bot.tree.command(name="listar-pqrs", description="[PROCURADURÍA] Ver todas las PQRS pendientes")
@es_procuraduria()
async def listar_pqrs(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    c.execute("SELECT radicado, tipo, asunto, estado FROM pqrs ORDER BY fecha_radicacion DESC LIMIT 20")
    pqrs_list = c.fetchall()
    conn.close()
    
    if not pqrs_list:
        await interaction.followup.send("📋 No hay PQRS registradas", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📋 Últimas 20 PQRS",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    for pqrs in pqrs_list:
        estado_emoji = "✅" if pqrs[3] == "RESPONDIDA" else "⏳"
        embed.add_field(
            name=f"{estado_emoji} {pqrs[0]}",
            value=f"**{pqrs[1]}** - {pqrs[2][:50]}...",
            inline=False
        )
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="ayuda", description="Ver comandos disponibles")
async def ayuda(interaction: discord.Interaction):
    rol = interaction.guild.get_role(ROL_PROCURADURIA_ID)
    es_procuraduria_user = rol in interaction.user.roles if rol else False
    
    embed = discord.Embed(
        title="📚 Comandos del Bot - Procuraduría",
        description="Lista de comandos disponibles",
        color=discord.Color.blue()
    )
    
    # Comandos para ciudadanos
    embed.add_field(
        name="👥 Comandos para Ciudadanos",
        value=(
            "`/buscar-caso` - Buscar caso por IUC\n"
            "`/radicar-pqrs` - Radicar PQRS\n"
            "`/consultar-radicado` - Ver estado de PQRS\n"
            "`/ayuda` - Ver esta ayuda"
        ),
        inline=False
    )
    
    # Comandos para procuraduría
    if es_procuraduria_user:
        embed.add_field(
            name="⚖️ Comandos para Procuraduría",
            value=(
                "`/registrar-documento` - Registrar resolución/decreto\n"
                "`/buscar-documento` - Buscar documento\n"
                "`/registrar-caso` - Registrar nuevo caso (IUC)\n"
                "`/responder-pqrs` - Responder PQRS\n"
                "`/listar-pqrs` - Ver PQRS pendientes"
            ),
            inline=False
        )
    
    embed.set_footer(text="Procuraduría General de la Nación")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="terminar-proceso", description="[PROCURADURÍA] Archivar un caso por IUC")
@app_commands.describe(radicado="Radicado IUC a archivar (ej: IUC-E-2025-0001)")
@es_procuraduria()
async def terminar_proceso(interaction: discord.Interaction, radicado: str):
    await interaction.response.defer(ephemeral=True)
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    c.execute("SELECT id, estado FROM casos WHERE iuc = ?", (radicado.upper(),))
    row = c.fetchone()
    if not row:
        conn.close()
        await interaction.followup.send("❌ No se encontró el caso.", ephemeral=True)
        return
    try:
        fecha_cierre = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("UPDATE casos SET estado = 'ARCHIVADO', fecha_cierre = ? WHERE id = ?", (fecha_cierre, row[0]))
        conn.commit()
        await interaction.followup.send(f"✅ Caso {radicado.upper()} archivado.", ephemeral=True)
        # Log en canal de registros
        try:
            channel = bot.get_channel(REGISTROS_CHANNEL_ID) or await bot.fetch_channel(REGISTROS_CHANNEL_ID)
            embed = discord.Embed(title="Proceso archivado", color=discord.Color.dark_blue(), timestamp=datetime.now())
            embed.add_field(name="IUC", value=radicado.upper(), inline=True)
            embed.add_field(name="Archivado por", value=interaction.user.name, inline=True)
            embed.add_field(name="Fecha", value=fecha_cierre, inline=False)
            await channel.send(embed=embed)
        except Exception:
            pass
    except Exception as e:
        await interaction.followup.send(f"❌ Error archivando el caso: {e}", ephemeral=True)
    finally:
        conn.close()
# ==================== EJECUTAR BOT ====================
if __name__ == "__main__":
    # Cargar variables de entorno
    try:
        from dotenv import load_dotenv
        load_dotenv()  # Solo en desarrollo local
    except:
        pass  # En Fly.io no necesita dotenv
    
    TOKEN = os.getenv('DISCORD_TOKEN')


@bot.tree.command(name="editar-iuc", description="[PROCURADURÍA] Editar la parte numérica final de un IUC (solo procuraduría)")
@app_commands.describe(
    iuc_actual="IUC actual a editar (ej: IUC-E-2025-0001)",
    nuevo_numero="Nuevo número (entero hasta 4 dígitos, se guardará como 4 dígitos con ceros)"
)
@es_procuraduria()
async def editar_iuc(interaction: discord.Interaction, iuc_actual: str, nuevo_numero: int):
    await interaction.response.defer(ephemeral=True)

    nuevo_numero = max(0, min(9999, int(nuevo_numero)))
    nuevo_numero_str = f"{nuevo_numero:04d}"

    # construir nuevo IUC reemplazando la última parte
    parts = iuc_actual.strip().split('-')
    if len(parts) < 2:
        await interaction.followup.send("Formato de IUC inválido.", ephemeral=True)
        return
    parts[-1] = nuevo_numero_str
    nuevo_iuc = '-'.join(parts).upper()

    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    # verificar que el caso existe
    c.execute("SELECT id FROM casos WHERE iuc = ?", (iuc_actual.upper(),))
    row = c.fetchone()
    if not row:
        await interaction.followup.send("No se encontró un caso con ese IUC.", ephemeral=True)
        conn.close()
        return

    # actualizar casos e documentos adjuntos
    try:
        c.execute("UPDATE casos SET iuc = ? WHERE id = ?", (nuevo_iuc, row[0]))
        c.execute("UPDATE documentos SET attached_iuc = ? WHERE attached_iuc = ?", (nuevo_iuc, iuc_actual.upper()))
        conn.commit()
        await interaction.followup.send(f"✅ IUC actualizado a {nuevo_iuc}. Documentos adjuntos actualizados.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Error actualizando IUC: {e}", ephemeral=True)
    finally:
        conn.close()
