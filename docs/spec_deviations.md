# Desviaciones entre la especificacion y la realidad

Registro de puntos donde `MCPearl_Especificaciones_Desarrollo.docx` promete algo
que el proveedor o la realidad tecnica no permiten. Cada entrada dice que decia
el documento, que se descubrio, y que se decidio.

Este fichero es la contrapartida honesta de la spec: si una desviacion no esta
aqui, el documento se considera vigente. Los tests de `tests/test_spec_compliance.py`
marcados BLOCKED referencian una entrada de este fichero.

---

## D01 — No se puede detener una llamada en curso

**Estado:** aceptada. Sin solucion tecnica.
**Descubierta en:** Fase 0, validacion del adaptador NLPearl.
**Afecta a:** seccion 6 (Condiciones de ejecucion), seccion 9 (Ejecucion robusta),
F09 (Control del usuario), A05 (Cancelacion o cambio de alcance).

### Que decia el documento

- Seccion 6: *"Si ya hay una llamada activa, solicitar su finalizacion y comunicar
  si esta pendiente."*
- Seccion 9: *"Resolver carreras entre cancelar y marcar; si ya empezo, pedir
  hangup y reflejar el resultado real."*
- A05: *"Cancelacion o cambio de alcance | Impide nuevas llamadas; informa si una
  llamada ya habia comenzado."*

### Que se descubrio

La API de NLPearl **no expone colgado por llamada individual**. Los unicos
mecanismos de parada son:

- `PUT /v2/Pearl/{id}/Active` — pausa el Pearl **entero**, no una llamada.
- Borrado de leads en cola — solo aplica a `add_lead` v2, no a `make_call`.

Pausar el Pearl entero no es una opcion: afectaria a las llamadas de todos los
demas usuarios que compartan ese Pearl. No hay forma de detener una llamada
concreta una vez enviada.

### Decision

Una llamada, una vez iniciada, **llega hasta el final**. No es un pendiente de
implementacion ni una limitacion temporal: es una propiedad del sistema.

En consecuencia:

- "Cancelar" significa **impedir llamadas futuras**, nunca interrumpir la que
  esta en curso. F09 se cumple solo para acciones futuras.
- Al cancelar con una llamada activa, el sistema informa de que hay una llamada
  en curso que **no puede detenerse**, y refleja su resultado real cuando
  termine. La segunda mitad de A05 ("informa si una llamada ya habia comenzado")
  sigue siendo exigible; la primera mitad, no.
- El texto de las secciones 6 y 9 debe corregirse en el .docx: donde dice
  "solicitar su finalizacion" y "pedir hangup", debe decir que se registra la
  imposibilidad y se espera el resultado.
- Esto tiene consecuencias de producto y de gasto: el coste de una llamada
  cancelada se consume igualmente. La tarifa debe contemplarlo.

### Pendiente

Pregunta abierta a soporte de NLPearl sobre la posibilidad de cancelar una
llamada en cola o en curso. Si algun dia existe, esta entrada se revisa.
