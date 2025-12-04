"""
Script de administración para el bot de Procuraduría
Permite gestionar la base de datos sin usar Discord
"""

import sqlite3
from datetime import datetime
import sys

def menu_principal():
    print("\n" + "="*50)
    print("ADMINISTRADOR - BOT PROCURADURÍA")
    print("="*50)
    print("1. Ver estadísticas")
    print("2. Listar todos los documentos")
    print("3. Listar todos los casos")
    print("4. Listar todas las PQRS")
    print("5. Buscar documento por número")
    print("6. Buscar caso por IUC")
    print("7. Eliminar documento")
    print("8. Actualizar estado de caso")
    print("9. Exportar base de datos a CSV")
    print("0. Salir")
    print("="*50)

def ver_estadisticas():
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM documentos")
    total_docs = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM casos")
    total_casos = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM pqrs")
    total_pqrs = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM pqrs WHERE estado = 'PENDIENTE'")
    pqrs_pendientes = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM pqrs WHERE estado = 'RESPONDIDA'")
    pqrs_respondidas = c.fetchone()[0]
    
    conn.close()
    
    print("\n📊 ESTADÍSTICAS")
    print(f"Total documentos: {total_docs}")
    print(f"Total casos (IUC): {total_casos}")
    print(f"Total PQRS: {total_pqrs}")
    print(f"  - Pendientes: {pqrs_pendientes}")
    print(f"  - Respondidas: {pqrs_respondidas}")

def listar_documentos():
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    c.execute("SELECT tipo, numero, anio, titulo FROM documentos ORDER BY anio DESC, numero DESC")
    docs = c.fetchall()
    conn.close()
    
    if not docs:
        print("\n❌ No hay documentos registrados")
        return
    
    print("\n📄 DOCUMENTOS REGISTRADOS")
    print("-" * 80)
    for doc in docs:
        print(f"{doc[0]} {doc[1]} de {doc[2]} - {doc[3]}")

def listar_casos():
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    c.execute("SELECT iuc, tipo, implicado, estado FROM casos ORDER BY fecha_apertura DESC")
    casos = c.fetchall()
    conn.close()
    
    if not casos:
        print("\n❌ No hay casos registrados")
        return
    
    print("\n📋 CASOS REGISTRADOS")
    print("-" * 80)
    for caso in casos:
        print(f"{caso[0]} - {caso[1]} - {caso[2]} - Estado: {caso[3]}")

def listar_pqrs():
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    c.execute("SELECT radicado, tipo, usuario_nombre, asunto, estado FROM pqrs ORDER BY fecha_radicacion DESC")
    pqrs_list = c.fetchall()
    conn.close()
    
    if not pqrs_list:
        print("\n❌ No hay PQRS registradas")
        return
    
    print("\n📨 PQRS REGISTRADAS")
    print("-" * 80)
    for pqrs in pqrs_list:
        print(f"{pqrs[0]} - {pqrs[1]} - {pqrs[2]}")
        print(f"  Asunto: {pqrs[3]}")
        print(f"  Estado: {pqrs[4]}")
        print()

def buscar_documento():
    numero = input("\nIngrese número de documento: ")
    
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    c.execute("SELECT * FROM documentos WHERE numero = ?", (numero,))
    docs = c.fetchall()
    conn.close()
    
    if not docs:
        print(f"\n❌ No se encontró documento con número {numero}")
        return
    
    for doc in docs:
        print(f"\n📄 {doc[1]} {doc[2]} de {doc[3]}")
        print(f"Título: {doc[4]}")
        print(f"Link: {doc[6]}")
        print(f"Registrado por: {doc[8]} el {doc[7]}")

def buscar_caso():
    iuc = input("\nIngrese IUC: ").upper()
    
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    c.execute("SELECT * FROM casos WHERE iuc = ?", (iuc,))
    caso = c.fetchone()
    conn.close()
    
    if not caso:
        print(f"\n❌ No se encontró caso {iuc}")
        return
    
    print(f"\n📋 Caso {caso[1]}")
    print(f"Tipo: {caso[2]}")
    print(f"Implicado: {caso[4]}")
    print(f"Estado: {caso[5]}")
    print(f"Descripción: {caso[6]}")
    print(f"Fecha apertura: {caso[7]}")

def eliminar_documento():
    numero = input("\nIngrese número de documento a eliminar: ")
    confirmar = input(f"¿Seguro que desea eliminar el documento {numero}? (s/n): ")
    
    if confirmar.lower() != 's':
        print("Operación cancelada")
        return
    
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    c.execute("DELETE FROM documentos WHERE numero = ?", (numero,))
    conn.commit()
    
    if c.rowcount > 0:
        print(f"✅ Documento {numero} eliminado")
    else:
        print(f"❌ No se encontró documento con número {numero}")
    
    conn.close()

def actualizar_estado_caso():
    iuc = input("\nIngrese IUC del caso: ").upper()
    
    print("\nEstados disponibles:")
    print("1. EN TRAMITE")
    print("2. EN INVESTIGACION")
    print("3. ARCHIVADO")
    print("4. SANCIONADO")
    print("5. ABSUELTO")
    
    opcion = input("Seleccione nuevo estado (1-5): ")
    
    estados = {
        '1': 'EN TRAMITE',
        '2': 'EN INVESTIGACION',
        '3': 'ARCHIVADO',
        '4': 'SANCIONADO',
        '5': 'ABSUELTO'
    }
    
    if opcion not in estados:
        print("❌ Opción inválida")
        return
    
    nuevo_estado = estados[opcion]
    
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    c.execute("UPDATE casos SET estado = ? WHERE iuc = ?", (nuevo_estado, iuc))
    conn.commit()
    
    if c.rowcount > 0:
        print(f"✅ Estado del caso {iuc} actualizado a: {nuevo_estado}")
    else:
        print(f"❌ No se encontró caso {iuc}")
    
    conn.close()

def exportar_csv():
    import csv
    
    conn = sqlite3.connect('procuraduria.db')
    c = conn.cursor()
    
    # Exportar documentos
    c.execute("SELECT * FROM documentos")
    docs = c.fetchall()
    with open('documentos_export.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['ID', 'Tipo', 'Numero', 'Anio', 'Titulo', 'Descripcion', 'Link', 'Fecha', 'Registrado_por'])
        writer.writerows(docs)
    
    # Exportar casos
    c.execute("SELECT * FROM casos")
    casos = c.fetchall()
    with open('casos_export.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['ID', 'IUC', 'Tipo', 'Anio', 'Implicado', 'Estado', 'Descripcion', 'Fecha_apertura'])
        writer.writerows(casos)
    
    # Exportar PQRS
    c.execute("SELECT * FROM pqrs")
    pqrs = c.fetchall()
    with open('pqrs_export.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['ID', 'Radicado', 'Tipo', 'Usuario_ID', 'Usuario_nombre', 'Asunto', 
                        'Descripcion', 'Estado', 'Fecha_radicacion', 'Fecha_respuesta', 
                        'Respuesta', 'Canal_mensaje_id'])
        writer.writerows(pqrs)
    
    conn.close()
    
    print("\n✅ Archivos exportados:")
    print("- documentos_export.csv")
    print("- casos_export.csv")
    print("- pqrs_export.csv")

def main():
    while True:
        menu_principal()
        opcion = input("\nSeleccione una opción: ")
        
        if opcion == '1':
            ver_estadisticas()
        elif opcion == '2':
            listar_documentos()
        elif opcion == '3':
            listar_casos()
        elif opcion == '4':
            listar_pqrs()
        elif opcion == '5':
            buscar_documento()
        elif opcion == '6':
            buscar_caso()
        elif opcion == '7':
            eliminar_documento()
        elif opcion == '8':
            actualizar_estado_caso()
        elif opcion == '9':
            exportar_csv()
        elif opcion == '0':
            print("\n👋 ¡Hasta luego!")
            sys.exit(0)
        else:
            print("\n❌ Opción inválida")
        
        input("\nPresione Enter para continuar...")

if __name__ == "__main__":
    main()