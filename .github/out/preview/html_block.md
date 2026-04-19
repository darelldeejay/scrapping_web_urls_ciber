```html
<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <title>[BANCO PICHINCHA - DORA] Informe diario de terceros ICT — 2026-04-19 (UTC)</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { 
            margin:0; padding:0; background:#f5f5f5; 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; 
            line-height: 1.6; color: #333;
        }
        .container { 
            max-width:800px; margin:20px auto; background:#ffffff; 
            border-radius:8px; overflow:hidden; 
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        
        /* Header corporativo elegante */
        .header-corporate { 
            background: linear-gradient(135deg, #1a365d 0%, #2b77ad 100%); 
            color: white; padding: 30px; text-align: center; 
        }
        .bank-title { 
            margin: 0; font-size: 26px; font-weight: 600; 
            letter-spacing: 0.5px;
        }
        .dora-subtitle { 
            margin: 8px 0 5px; font-size: 16px; opacity: 0.9; 
            font-weight: 300;
        }
        .report-meta { 
            margin: 15px 0 0; padding: 12px; 
            background: rgba(255,255,255,0.15); border-radius: 4px; 
            font-size: 14px; font-weight: 300;
        }

        /* Dashboard KPI limpio */
        .dashboard { 
            background: #f8f9fa; padding: 30px; 
            display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); 
            gap: 15px;
        }
        .kpi-card { 
            background: white; padding: 20px; border-radius: 6px; 
            text-align: center; border-left: 3px solid #dee2e6;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            transition: border-left-color 0.2s;
        }
        .kpi-card:hover { border-left-color: #007bff; }
        .kpi-number { 
            font-size: 32px; font-weight: 600; margin-bottom: 8px; color: #2c3e50;
        }
        .kpi-label { 
            font-size: 11px; color: #6c757d; text-transform: uppercase; 
            letter-spacing: 0.8px; font-weight: 500;
        }

        /* Content sections */
        .content-section { 
            padding: 30px; border-bottom: 1px solid #eee;
        }
        .content-section:last-child { border-bottom: none; }
        .section-title { 
            font-size: 20px; font-weight: 600; margin: 0 0 20px; 
            color: #2c3e50; 
        }
        
        /* Risk assessment elegante */
        .risk-assessment { 
            background: #f8f9fa; border: 1px solid #dee2e6; 
            border-radius: 6px; padding: 25px; margin: 20px 0;
            border-left: 4px solid #17a2b8;
        }
        .risk-title { 
            margin: 0 0 12px; color: #2c3e50; font-size: 16px; 
            font-weight: 600;
        }
        .risk-content {
            color: #495057; font-size: 15px; line-height: 1.6;
        }

        /* VENDOR DETAILS MEJORADOS - NUEVA SECCIÓN */
        .vendor-details-improved {
            background: #ffffff; 
            border: 1px solid #dee2e6; 
            border-radius: 8px; 
            margin: 20px 0;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }

        .vendor-header {
            background: linear-gradient(90deg, #e9ecef 0%, #f8f9fa 100%);
            padding: 15px 25px;
            border-bottom: 1px solid #dee2e6;
            font-weight: 600;
            font-size: 14px;
            color: #495057;
            letter-spacing: 0.5px;
        }

        .vendor-content {
            background: #fafbfc; 
            padding: 25px; 
            margin: 0;
            font-family: 'SF Mono', Consolas, 'Courier New', monospace; 
            font-size: 13px; 
            line-height: 1.8;
            white-space: pre-wrap;
            word-break: break-word;
            border: none;
            color: #2c3e50;
        }

        /* Separadores visuales para fabricantes */
        .vendor-content::before {
            content: "";
            display: block;
            height: 2px;
            background: linear-gradient(90deg, #17a2b8 0%, transparent 100%);
            margin: -10px 0 15px 0;
        }

        /* Recommendations limpias */
        .recommendations { 
            display: grid; grid-template-columns: 1fr; gap: 20px; 
            margin: 25px 0;
        }
        .recommendation-item { 
            padding: 20px; border-radius: 6px; 
            border: 1px solid #dee2e6; background: #fafbfc;
        }
        .recommendation-title {
            font-weight: 600; color: #2c3e50; margin-bottom: 8px;
        }
        .recommendation-content {
            color: #495057; line-height: 1.5;
        }

        /* Sources profesionales */
        .sources-list { 
            columns: 2; column-gap: 25px; 
        }
        .sources-list li { 
            break-inside: avoid; margin-bottom: 10px;
            color: #495057;
        }
        .sources-list a {
            color: #007bff; text-decoration: none;
        }
        .sources-list a:hover {
            text-decoration: underline;
        }

        /* Footer corporativo */
        .footer-corporate { 
            background: #343a40; color: #fff; padding: 25px; 
        }
        .footer-content { 
            text-align: center; line-height: 1.5;
        }
        .footer-main { 
            margin-bottom: 15px; font-size: 14px;
        }
        .footer-compliance { 
            font-size: 12px; opacity: 0.8; border-top: 1px solid #495057;
            padding-top: 15px; margin-top: 15px;
        }

        /* Responsive design */
        @media (max-width: 600px) {
            .dashboard { grid-template-columns: repeat(2, 1fr); }
            .sources-list { columns: 1; }
            .container { margin: 10px; }
            .header-corporate { padding: 20px; }
            .content-section { padding: 20px; }
            .vendor-content { font-size: 12px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header Corporativo -->
        <header class="header-corporate">
            <h1 class="bank-title">BANCO PICHINCHA</h1>
            <h2 class="dora-subtitle">Digital Operational Resilience Act</h2>
            <p style="margin: 5px 0; font-size: 15px;">Monitoreo de Terceros ICT</p>
            <div class="report-meta">
                <strong>2026-04-19 | 10:48 (UTC)</strong><br>
                Ventana de observación: 2026-04-19 00:00–2026-04-19 10:44
            </div>
        </header>

        <!-- Dashboard Ejecutivo -->
        <section class="dashboard">
            <div class="kpi-card">
                <div class="kpi-number">8</div>
                <div class="kpi-label">Proveedores ICT</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-number">3</div>
                <div class="kpi-label">Nuevos Hoy</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-number">0</div>
                <div class="kpi-label">Incidentes Activos</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-number">4</div>
                <div class="kpi-label">Resueltos Hoy</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-number">5</div>
                <div class="kpi-label">Mantenimientos</div>
            </div>
        </section>

        <!-- Introducción -->
        <section class="content-section">
            <p style="font-size: 16px; margin-bottom: 15px; color: #495057;">Buenos días,</p>
            <p style="color: #6c757d; line-height: 1.6;">
                Presentamos el informe diario de monitoreo de terceros tecnológicos en cumplimiento 
                con los requisitos de resiliencia operativa digital establecidos por DORA.
            </p>
        </section>

        <!-- Evaluación de Riesgo -->
        <section class="content-section">
            <div class="risk-assessment">
                <h3 class="risk-title">Evaluación de Riesgo Operacional (DORA)</h3>
                <div class="risk-content">Incidencias en curso en una o más plataformas. Revisión recomendada.</div>
            </div>
        </section>

        <!-- Estado de Proveedores MEJORADO -->
        <section class="content-section">
            <h2 class="section-title">Estado Detallado por Proveedor ICT</h2>
            
            <div class="vendor-details-improved">
                <div class="vendor-header">
                    ESTADO OPERACIONAL POR FABRICANTE
                </div>
                <pre class="vendor-content">=== AKAMAI (GUARDICORE) ===
Akamai (Guardicore) - Status
2026-04-19 10:41 UTC

Component status
- Content Delivery Operational
- App & Network Security Operational
- Enterprise Security Operational
- Data Services Operational
- Configuration Operational
- Customer Service, Documentation and Community Operational

Incidents today
No incidents reported today.

=== ARUBA CENTRAL ===
Aruba Central - Status
2026-04-19 10:40 UTC

Component status
- All components Operational

Incidents today
No incidents reported today.

=== CYBERARK PRIVILEGE CLOUD ===
CyberArk Privilege Cloud - Status
2026-04-19 10:41 UTC

Component status
- (no data)

Incidents today
No incidents reported today.

=== IMPERVA ===
Imperva - Status
2026-04-19 10:40 UTC

Component status
- Coming Soon: Under Maintenance
- Tokyo, Japan (NRT) - May 2026: Under Maintenance
- Amsterdam, Netherlands (RTM) - May 2026: Under Maintenance
- Frankfurt, Germany (HHN) - April 2026: Under Maintenance
- Singapore (XSP) - May 2026: Under Maintenance

Incidents today
- Incident
- update — [PPNG-3294] - Scheduled update to the Cloud Security Console – April 19, 2026
- [ICM-4875] Planned maintenance on the Imperva data center in New York 2, NY [POPs: 2026, 4875, ICM, UTC]
- [ICM-4904] Planned maintenance on the Imperva data center in Houston, TX [POPs: 2026, 4904, ICM, UTC]
- [ICM-4910] Essential Maintenance on the Imperva data center in Hanoi, Vietnam [POPs: 2026, 4910, ICM, UTC]
- update — [UM-13107] - Scheduled update to the Cloud Security Console – April 26, 2026
- [ICM-4906] Planned Maintenance on the Imperva data center in Paris 2, France [POPs: 2026, 4906, ICM, UTC]

=== NETSKOPE ===
Netskope - Estado de Incidentes
2026-04-19 10:39 UTC

Component status
- All components Operational

Incidents today
Incidentes activos
- No hay incidentes activos reportados.
Últimos 15 días (resueltos)
- (no data)

=== PROOFPOINT ===
Proofpoint - Estado de Incidentes
2026-04-19 10:40 UTC

Component status
- All components Operational

Incidents today
Incidentes activos
- No hay incidentes activos reportados.

=== QUALYS ===
Qualys - Estado de Incidentes
2026-04-19 10:40 UTC

Component status
- (no data)

Incidents today
Histórico (meses visibles en la página)
1. EU Platform 2: Delay in VM Scan Processing [IM-12595] (https://status.qualys.com/incidents/968bp3gydmf0)
   Estado: Resolved · Inicio: 2026-04-16 23:43 UTC · Fin: 2026-04-17 09:50 UTC
2. EU Platform 2: Qualys UI Login Impacted [IM-12553]
   Estado: Resolved · Inicio: 2026-03-24 03:05 UTC · Fin: 2026-03-24 06:23 UTC
3. Platform: US_POD1/2/3, EU_POD1/2, IN_POD1, CA_POD1: Tag Based Queries Not Returning Expected Assets(IM-12549) (https://status.qualys.com/incidents/shjmjqtr2l9n)
   Estado: Resolved · Inicio: 2026-03-18 03:11 UTC · Fin: 2026-03-22 12:16 UTC
4. EU2 : Observing issue with VM/PA scheduled scans and reports (IM-12524) (https://status.qualys.com/incidents/9sm72pyhqqd2)
   Estado: Resolved · Inicio: 2026-02-28 08:08 UTC · Fin: 2026-02-28 13:43 UTC

=== TREND MICRO ===
Trend Micro - Status
2026-04-19 10:41 UTC

Component status
- All components Operational

[Trend Cloud One]
Incidents today
- No incidents reported today.
[Trend Vision One]
Incidents today
- No incidents reported today.</pre>
            </div>
            
            <p style="font-size: 12px; color: #6c757d; margin-top: 15px;">
                <strong>Fuente:</strong> Páginas de estado oficiales | 
                <strong>Alcance:</strong> 8 proveedores críticos |
                <strong>Actualización:</strong> Tiempo real con conversión a UTC
            </p>
        </section>

        <!-- Recomendaciones -->
        <section class="content-section">
            <h2 class="section-title">Recomendaciones Operativas</h2>
            <div class="recommendations">
                <div class="recommendation-item">
                    <div class="recommendation-title">Impacto en Servicios del Cliente</div>
                    <div class="recommendation-content">Sí (potencial)</div>
                </div>
                <div class="recommendation-item">
                    <div class="recommendation-title">Acción Sugerida</div>
                    <div class="recommendation-content">Comunicación interna breve; monitorización reforzada; revisión de alertas SIEM/observabilidad; seguimiento con el/los fabricante(s) hasta resolución.</div>
                </div>
                <div class="recommendation-item">
                    <div class="recommendation-title">Próxima Revisión Programada</div>
                    <div class="recommendation-content">2026-04-20 (UTC)</div>
                </div>
            </div>
        </section>

        <!-- Fuentes -->
        <section class="content-section">
            <h2 class="section-title">Fuentes Monitorizadas</h2>
            <ul class="sources-list">
                <li><a href="https://centralstatus.arubanetworking.hpe.com/">Aruba Central — Status</a></li>
<li><a href="https://privilegecloud-service-status.cyberark.com/">CyberArk Privilege Cloud — Status</a></li>
<li><a href="https://www.akamaistatus.com/">Akamai (Guardicore) — Status</a></li>
<li><a href="https://status.imperva.com/">Imperva — Status</a></li>
<li><a href="https://trustportal.netskope.com/incidents">Netskope — Trust Portal</a></li>
<li><a href="https://proofpoint.my.site.com/community/s/proofpoint-current-incidents">Proofpoint — Current Incidents</a></li>
<li><a href="https://status.qualys.com/history?filter=8f7fjwhmd4n0">Qualys — Status History</a></li>
<li><a href="https://status.trendmicro.com/">Trend Micro — Status</a></li>

            </ul>
        </section>

        <!-- Footer -->
        <footer class="footer-corporate">
            <div class="footer-content">
                <div class="footer-main">
                    <strong>Soporte Técnico SOC</strong><br>
                    Para escalamiento urgente o consultas técnicas detalladas, nuestro equipo especializado 
                    está disponible para asistencia inmediata.
                </div>
                <div class="footer-compliance">
                    <strong>Cumplimiento DORA:</strong> Este reporte cumple con el Article 28 sobre monitoreo de terceros<br>
                    <strong>Confidencial:</strong> Información exclusiva para uso interno Banco Pichincha<br>
                    
                </div>
            </div>
        </footer>
    </div>
</body>
</html>

```