## 📊 Estrategia y Umbrales de Indicadores

El bot utiliza principalmente el **RSI (Relative Strength Index)** y la **Media Móvil (MA7)** para la toma de decisiones. A continuación, se detallan los umbrales configurados para las operaciones de DCA:

### 1. Umbrales del RSI (Temporalidad: 1h/4h)
El RSI mide la fuerza del precio. Los multiplicadores ajustan el monto de compra base según el nivel de sobreventa.

| Nivel RSI | Estado del Mercado | Acción del Bot | Multiplicador |
| :--- | :--- | :--- | :--- |
| **> 70** | Sobrecompra | `DCA_SELL` / Pausa Compra | - |
| **40 - 60** | Neutral | Compra Estándar | x1.0 |
| **25 - 35** | Sobreventa | **TURBO_BUY** | x1.6 |
| **< 20** | Capitulación | **EXTREME_BUY** | x2.0 |

### 2. Filtro de Media Móvil (MA7)
Para evitar compras en picos locales, el bot valida el precio contra la media de los últimos 7 días:
* **Condición de Compra:** `Precio Actual < 97% de MA7`.
* Esto asegura que solo compramos si el precio tiene al menos un **3% de descuento** respecto al promedio semanal.

### 3. Gestión de Datos
* **Señales:** Se almacenan en la base de datos local para seguimiento de rendimiento.
* **Limpieza:** Se recomienda purgar registros antiguos mensualmente para optimizar el rendimiento del servidor Linux.