# HMI golden set: review sheet

Tick each item after checking the quote in the PDF.

## A01 · spec

**Q:** What is the maximum power consumption of the PanelView 800 7-inch terminal, catalog number 2711R-T7T?

**Expected:** The 2711R-T7T draws a maximum of 11 W (0.40 A @ 24V DC).

- `hmi/allen-bradley/panelview-800/panelview_800_technical_data.pdf` p.5: "Power Consumption (max) 9 W (0.39 A @ 24V DC) 11 W (0.40 A @ 24V DC) 14 W (0.48 A @ 24V DC)"
- ⚠ Value picked by column position in a flattened power table (9/11/14 W); confirm 11 W is the T7T column.
- sources (any): hmi/allen-bradley/panelview-800/panelview_800_technical_data.pdf

- [x] OK   - [ ] fix: 

## A02 · spec

**Q:** Which replacement battery should be used for the real-time clock in a PanelView 800 terminal (2711R-T4T/T7T/T10T)?

**Expected:** Replace it only with catalog number 2711P-Y2032 or a manufacturer's equivalent such as the Matsushita or Duracell DL2032 lithium battery.

- `hmi/allen-bradley/panelview-800/panelview_800_user_manual.pdf` p.130: "only replace the battery with 2711P-Y2032 or a manufacturer"
- sources (any): hmi/allen-bradley/panelview-800/panelview_800_user_manual.pdf

- [x] OK   - [ ] fix: 

## A03 · spec

**Q:** At what CPU temperature does a PanelView 5310 terminal go into an over-temperature condition that triggers a delayed automatic restart?

**Expected:** An over-temperature condition of 105…110 °C (221…230 °F) causes a delayed automatic system restart (normal CPU temperature is 25…94 °C).

- `hmi/allen-bradley/panelview-5310/panelview_5310_user_manual.pdf` p.62: "An over-temperature condition of 105…110 °C (221…230 °F) causes a delayed automatic system restart."
- sources (any): hmi/allen-bradley/panelview-5310/panelview_5310_user_manual.pdf

- [x] OK   - [ ] fix: 

## A04 · spec

**Q:** What is the heat dissipation of a 12-inch PanelView Plus 7 Standard terminal such as the 2711P-T12W21D8S?

**Expected:** The 12 in. PanelView Plus 7 Standard terminal dissipates 30 W = 102 BTU.

- `hmi/allen-bradley/panelview-plus7/panelview_plus7_standard_technical_data.pdf` p.2: "10 in., 20 W= 68 BTU 12 in., 30 W= 102 BTU"
- sources (any): hmi/allen-bradley/panelview-plus7/panelview_plus7_standard_technical_data.pdf

- [x] OK   - [ ] fix: 

## A05 · spec

**Q:** What is the minimum real-time clock battery voltage considered normal on a PanelView Plus 7 Performance terminal?

**Expected:** The battery voltage must be at least 2.75V DC; 2.75V or higher is Normal (2.0…2.74V is Low, below 2.0V is Depleted).

- `hmi/allen-bradley/panelview-plus7/panelview_plus7_performance_user_manual.pdf` p.92: "Battery voltage must be at least 2.75V DC."
- `hmi/allen-bradley/panelview-plus7/panelview_plus7_performance_user_manual.pdf` p.114: "Low 2.0…2.74V Normal 2.75V or higher"
- sources (any): hmi/allen-bradley/panelview-plus7/panelview_plus7_performance_user_manual.pdf

- [x] OK   - [ ] fix: 

## A06 · spec

**Q:** What ATEX certificate number covers the non-display VersaView 5200 thin client, catalog number 6200T-NA?

**Expected:** It is covered by ATEX certificate DEMKO 19 ATEX 2252 X (marking II 3 G, Ex ec IIC T4 Gc), issued by UL International Demko A/S. The installation instructions also list a separate UK (UKEX) certificate UL21UKEX2323X and a China CCC certificate; mentioning those alongside is fine, but giving UL21UKEX2323X as the ATEX number is wrong.

- `hmi/allen-bradley/versaview-5000/versaview_5000_declaration_of_conformity.pdf` p.1: "Type Examination Certificate No. Demko 19 ATEX 2252 X issued by UL"
- `hmi/allen-bradley/versaview-5000/industrial_computers_and_monitors_technical_data.pdf` p.8: "Europe (ATEX) II 3 G, Ex ec IIC T4 Gc, DEMKO 19 ATEX 2252 X"
- `hmi/allen-bradley/versaview-5000/versaview_5000_installation_instructions.pdf` p.3: "Europe (ATEX) II 3 G, Ex ec IIC T4 Gc, DEMKO 19 ATEX 2252 X"
- `hmi/allen-bradley/versaview-5000/versaview_5000_thin_clients_and_industrial_computers_user_manual.pdf` p.19: "Europe (ATEX) II 3 G, Ex ec IIC T4 Gc, DEMKO 19 ATEX 2252 X"
- difficulty: distractor
- ⚠ Only the installation instructions (a newer revision) carry the UK line 'United Kingdom (UK) II 3 G, Ex ec IIC T4 Gc, UL21UKEX2323X' and a China CCC line; the other three documents list US, Canada and Europe only. The UKEX number is a sibling certificate, not the ATEX one.
- sources (any): hmi/allen-bradley/versaview-5000/versaview_5000_declaration_of_conformity.pdf, hmi/allen-bradley/versaview-5000/industrial_computers_and_monitors_technical_data.pdf, hmi/allen-bradley/versaview-5000/versaview_5000_installation_instructions.pdf, hmi/allen-bradley/versaview-5000/versaview_5000_thin_clients_and_industrial_computers_user_manual.pdf

- [x] OK   - [ ] fix: 

## A07 · spec

**Q:** What ingress protection rating does a VersaView 5100 industrial monitor (e.g. 6200M-15WBN) have when it is VESA-mounted instead of panel-mounted?

**Expected:** VESA mounting reduces the monitor's IP rating from IP66 to IP20 (VESA Mount: IEC IP20; Panel Mount: NEMA 4X, IEC IP66).

- `hmi/allen-bradley/versaview-5100/versaview_5100_industrial_monitors_user_manual.pdf` p.19: "If you choose to VESA mount a monitor, its IP rating is reduced from IP66 to IP20."
- `hmi/allen-bradley/versaview-5000/industrial_computers_and_monitors_technical_data.pdf` p.31: "Enclosure ratings VESA Mount: IEC IP20 Panel Mount: NEMA 4X, IEC IP66"
- sources (any): hmi/allen-bradley/versaview-5100/versaview_5100_industrial_monitors_user_manual.pdf, hmi/allen-bradley/versaview-5000/industrial_computers_and_monitors_technical_data.pdf

- [x] OK   - [ ] fix: 

## A08 · spec

**Q:** What is the operating temperature range of an ASEM 6300P panel PC fitted with a Core i7 processor?

**Expected:** 0…45 °C (32…113 °F) with a Core i7 processor (versus 0…50 °C with Core i3); the i7 throttles above 45 °C under heavy load.

- `hmi/allen-bradley/asem-6300/asem_6300p_panel_pcs_technical_data.pdf` p.5: "0…45 °C (32…113 °F) with Core i7 processor"
- `hmi/allen-bradley/asem-6300/asem_6300_monitors_pcs_thin_clients_technical_data.pdf` p.21: "0…45 °C (32…113 °F) with Core i7 processor"
- `hmi/allen-bradley/asem-6300/asem_6300p_panel_pcs_user_manual.pdf` p.14: "The Intel Core i7 processor throttles above 45 °C (113 °F) when the CPU is heavily loaded."
- sources (any): hmi/allen-bradley/asem-6300/asem_6300p_panel_pcs_technical_data.pdf, hmi/allen-bradley/asem-6300/asem_6300_monitors_pcs_thin_clients_technical_data.pdf, hmi/allen-bradley/asem-6300/asem_6300p_panel_pcs_user_manual.pdf

- [x] OK   - [ ] fix: 

## A09 · spec

**Q:** How much RAM and user application storage does the PanelView 5500 6.5-inch terminal 2715-T7CD have?

**Expected:** 512 MB RAM and 250 MB nonvolatile storage for projects.

- `hmi/allen-bradley/panelview-5500/panelview_5500_technical_data.pdf` p.3: "512 MB RAM 250 MB nonvolatile storage for projects"
- `hmi/allen-bradley/panelview-5500/panelview_5500_user_manual.pdf` p.16: "TFT Color Yes DC 512 MB 250 MB 2715-T7CA"
- sources (any): hmi/allen-bradley/panelview-5500/panelview_5500_technical_data.pdf, hmi/allen-bradley/panelview-5500/panelview_5500_user_manual.pdf

- [x] OK   - [ ] fix: 

## A10 · comparison

**Q:** Which has the higher maximum operating temperature: the PanelView 5500 2715-T10CD or the PanelView 800 2711R-T10T?

**Expected:** The PanelView 5500 2715-T10CD, rated 0…55 °C (32…131 °F), versus 0…50 °C (32…122 °F) for the PanelView 800 2711R-T10T.

- `hmi/allen-bradley/panelview-5500/panelview_5500_technical_data.pdf` p.2: "Temperature, operating 0…55 °C (32…131 °F)"
- `hmi/allen-bradley/panelview-5500/panelview_5500_user_manual.pdf` p.24: "The ambient temperature around the terminal must be 0…55 °C (32…131 °F)."
- `hmi/allen-bradley/panelview-800/panelview_800_technical_data.pdf` p.3: "0…50 °C (32…122 °F) Temperature, nonoperating"
- sources (all): hmi/allen-bradley/panelview-5500/panelview_5500_technical_data.pdf, hmi/allen-bradley/panelview-5500/panelview_5500_user_manual.pdf, hmi/allen-bradley/panelview-800/panelview_800_technical_data.pdf

- [x] OK   - [ ] fix: 

## A11 · comparison

**Q:** How does the ingress protection rating of the PanelView 5510 stainless-steel terminal 2715P-T12WD-BSK differ from the PanelView 5510 capacitive-touch terminal 2715P-C12WD?

**Expected:** The stainless-steel terminal is rated IP69 (classified by UL) and tested for IP69K per ISO 20653, while the capacitive-touch terminal is rated IP65 according to IEC 60529.

- `hmi/allen-bradley/panelview-5510/panelview_5510_technical_data.pdf` p.3: "Rated IP69 as Classified by UL. Tested for IP69K according to ISO 20653."
- `hmi/allen-bradley/panelview-5510/panelview_5510_technical_data.pdf` p.3: "NEMA and UL Type 1, 4X, and 12. Rated IP65 according to IEC 60529."
- ⚠ IP69 vs IP65 mapped by column order in a flattened table on p.3; confirm against the PDF.
- sources (all): hmi/allen-bradley/panelview-5510/panelview_5510_technical_data.pdf

- [x] OK   - [ ] fix: 

## A12 · comparison

**Q:** How many Ethernet ports does the PanelView 5310 have compared with the PanelView 5510, and which supports Device Level Ring (DLR)?

**Expected:** The PanelView 5310 has one 10/100Base-T Ethernet port, while the PanelView 5510 has two 10/100Base-T Ethernet ports that support DLR (as well as linear and star) topologies.

- `hmi/allen-bradley/panelview-5310/panelview_5310_technical_data.pdf` p.4: "One 10/100Base-T, Auto MDI/MDI-X Ethernet port for controller communication."
- `hmi/allen-bradley/panelview-5310/panelview_5310_user_manual.pdf` p.12: "One 10/100Base-T, Auto MDI/MDI-X, EtherNet/IP port for controller communication."
- `hmi/allen-bradley/panelview-5510/panelview_5510_technical_data.pdf` p.4: "Two 10/100Base-T, Auto MDI/MDIX Ethernet ports that support (Device Level Ring) DLR, linear, or star network topologies."
- `hmi/allen-bradley/panelview-5510/panelview_5510_user_manual.pdf` p.10: "Two 10/100Base-T, Auto MDI/MDIX, EtherNet/IP ports for controller communication that supports DLR network topology."
- sources (all): hmi/allen-bradley/panelview-5310/panelview_5310_technical_data.pdf, hmi/allen-bradley/panelview-5310/panelview_5310_user_manual.pdf, hmi/allen-bradley/panelview-5510/panelview_5510_technical_data.pdf, hmi/allen-bradley/panelview-5510/panelview_5510_user_manual.pdf

- [x] OK   - [ ] fix: 

## B01 · spec

**Q:** What is the power consumption of the SIMATIC KTP1200 Basic DP (Basic Panels 2nd Generation)?

**Expected:** The KTP1200 Basic DP has a power consumption of 13.2 W (the KTP1200 Basic PN variant is 12.2 W).

- `hmi/siemens/ktp-basic/ktp_basic_panels_2nd_gen_hardware.pdf` p.119: "Power consumption 1 
5.5 W 
12.2 W 
13.2 W"
- ⚠ Value mapped to the model by column order in a flattened table; confirm against the PDF.
- sources (any): hmi/siemens/ktp-basic/ktp_basic_panels_2nd_gen_hardware.pdf

- [x] OK   - [ ] fix: 

## B02 · spec

**Q:** How much power does the MTP1900 Unified Comfort panel draw at 24 V DC without loads?

**Expected:** The MTP1900 Unified Comfort has a power consumption without loads of 28.8 W (rated current 1.2 A at 24 V DC without loads).

- `hmi/siemens/unified-comfort-mtp/unified_comfort_panels_operating_instructions.pdf` p.159: "Rated current at 24 V DC, without loads 
0.7 A 
1.2 A 
1.0 A"
- `hmi/siemens/unified-comfort-mtp/unified_comfort_panels_operating_instructions.pdf` p.159: "Power consumption, without loads 1 
16.8 W 
28.8 W 
24.0 W"
- sources (any): hmi/siemens/unified-comfort-mtp/unified_comfort_panels_operating_instructions.pdf

- [x] OK   - [ ] fix: 

## B03 · spec

**Q:** What is the display resolution of the SIMATIC TP2200 Comfort panel?

**Expected:** The TP2200 Comfort has a 21.5'' display with a resolution of 1920 x 1080 pixels.

- `hmi/siemens/tp-comfort/tp_comfort_panels_hardware_manual.pdf` p.221: "Resolution 
1280 x 800 pixels 
1366 x 768 pixels 
1920 x 1080 pixels"
- `hmi/siemens/tp-comfort/tp_comfort_panels_operating_instructions.pdf` p.193: "Resolution 
1280 x 800 pixels 
1366 x 768 pixels 
1920 x 1080 pixels"
- ⚠ Value mapped to the model by column order in a flattened table; confirm against the PDF.
- sources (any): hmi/siemens/tp-comfort/tp_comfort_panels_hardware_manual.pdf, hmi/siemens/tp-comfort/tp_comfort_panels_operating_instructions.pdf

- [x] OK   - [ ] fix: 

## B04 · spec

**Q:** What is the power consumption of the SIMATIC IFP2400 V2 (24") industrial flat panel?

**Expected:** The 24" IFP V2 device has a power consumption of 36 W (rated voltage 24 V DC, permitted range +19.2 V ... +28.8 V).

- `hmi/siemens/ifp-v2/ifp_v2_operating_instructions.pdf` p.126: "Power consumption 1 
15.6 W 
24 W 
29 W 
24 W 
36 W"
- sources (any): hmi/siemens/ifp-v2/ifp_v2_operating_instructions.pdf

- [x] OK   - [ ] fix: 

## B05 · spec

**Q:** In WinCC Unified Runtime, is the script debugger enabled by default, and what are the default port numbers for the screen debugger and the job (scheduler) debugger?

**Expected:** The debugger is disabled by default; the default port is 9222 for the screen debugger and 9224 for the job debugger (both TCP).

- `hmi/siemens/wincc-unified/wincc_unified_runtime_system_manual.pdf` p.233: "The debugger is disabled by default."
- `hmi/siemens/wincc-unified/wincc_unified_runtime_system_manual.pdf` p.233: "Assign an available port number to the debugger for screens (default port number: 9222)."
- `hmi/siemens/wincc-unified/wincc_unified_runtime_system_manual.pdf` p.233: "Assign an available port number to the debugger for jobs (default port number: 9224)."
- `hmi/siemens/wincc-unified/wincc_unified_runtime_system_manual.pdf` p.8: "Screen debugger 
9222 
TCP 
Job debugger 
9224 
TCP"
- sources (any): hmi/siemens/wincc-unified/wincc_unified_runtime_system_manual.pdf

- [x] OK   - [ ] fix: 

## B06 · spec

**Q:** How many tags can the WinCC Unified Runtime tag simulator simulate at the same time?

**Expected:** A maximum of 300 tags can be simulated at the same time, although more tags can be configured and saved in the simulator.

- `hmi/siemens/wincc-unified/wincc_unified_runtime_system_manual.pdf` p.291: "A maximum of 300 tags can be simulated at the same time.
However, you can configure and save more tags in the simulator."
- `hmi/siemens/wincc-unified/wincc_unified_runtime_system_manual.pdf` p.294: "A maximum of 300 tags can be simulated at the same 
time."
- `hmi/siemens/wincc-unified/wincc_unified_runtime_system_manual.pdf` p.297: "You can simulate a maximum of 300 tags simultaneously, even if more tags are configured"
- sources (any): hmi/siemens/wincc-unified/wincc_unified_runtime_system_manual.pdf

- [x] OK   - [ ] fix: 

## B07 · spec

**Q:** What ambient temperature range is permitted during operation for a Beckhoff CP3716 panel PC (CP37xx series)?

**Expected:** Operation: 0 °C to +45 °C (transport/storage: -20 °C ... +65 °C).

- `hmi/beckhoff/cp3xxx-series/cp37xx_panel_pc_manual.pdf` p.47: "Permissible ambient temperature
Operation: 0 °C to +45 °C
Transport / storage: -20 °C ... +65 °C"
- sources (any): hmi/beckhoff/cp3xxx-series/cp37xx_panel_pc_manual.pdf

- [x] OK   - [ ] fix: 

## B08 · spec

**Q:** Does the Beckhoff CP6700-0001-0050 panel PC have fTPM 2.0 enabled?

**Expected:** No. The CP6700-0001-0050 has fTPM 2.0 not enabled; the CP6700-0001-0060 and CP6700-0001-0070 have fTPM 2.0 enabled.

- `hmi/beckhoff/cp6000-series/cp6700_panel_pc.pdf` p.40: "CP6700-0001-0050: fTPM 2.0 not enabled
CP6700-0001-0060: fTPM 2.0 enabled
CP6700-0001-0070: fTPM 2.0 enabled"
- sources (any): hmi/beckhoff/cp6000-series/cp6700_panel_pc.pdf

- [x] OK   - [ ] fix: 

## B09 · spec

**Q:** What are the dimensions (W x H x D) of the Advantech WebOP-2080V (WOP-2080V-N4AE) operator panel?

**Expected:** 232.5 x 175.8 x 42.9 mm (9.15" x 6.92" x 1.69").

- `hmi/advantech/webop-3000t/advantech_industrial_operator_panels_catalog.pdf` p.1: "232.5 x 175.8 x 42.9mm 
(9.15" x 6.92" x 1.69")"
- sources (any): hmi/advantech/webop-3000t/advantech_industrial_operator_panels_catalog.pdf

- [x] OK   - [ ] fix: 

## B10 · comparison

**Q:** How does the permitted DC supply voltage of the SIMATIC IFP1500 Basic compare with that of its second-generation successor, the SIMATIC HMI IM-315A?

**Expected:** The IFP1500 Basic is rated 24 V DC with a permitted range of +20.4 V to +28.8 V, whereas the IM-315A takes nominal 12-24 V DC (min. 9 V to max. 36 V), a much wider input range.

- `hmi/siemens/ifp-basic/ifp_basic_operating_instructions.pdf` p.68: "Rated voltage 
Permitted voltage 
range 
24 V DC 
+20.4 V to + 28.8 V"
- `hmi/siemens/industrial-monitors-im/im312a_315a_319a_322a_operating_instructions.pdf` p.52: "Voltage 
Nominal 12-24 V DC (Min.9 V to Max.36 V)"
- sources (all): hmi/siemens/ifp-basic/ifp_basic_operating_instructions.pdf, hmi/siemens/industrial-monitors-im/im312a_315a_319a_322a_operating_instructions.pdf

- [x] OK   - [ ] fix: 

## B11 · comparison

**Q:** Compare the front and rear degree of protection of a Siemens MTP1500 Unified Comfort panel with a Beckhoff CP6600-0001-0020 panel PC.

**Expected:** The Unified Comfort panel (e.g. MTP1500) is IP65 at the front when mounted (plus UL50 Type 4X/Type 12 front face) and IP20 at the rear; the Beckhoff CP6600-0001-0020 is rated front IP54, rear IP20.

- `hmi/siemens/unified-comfort-mtp/unified_comfort_panels_operating_instructions.pdf` p.150: "IP65 according to IEC 60529 
• 
Type 4X/Type 12 (indoor use only, front face only) according to 
UL50 
Rear 
IP20"
- `hmi/beckhoff/cp6000-series/cp6600_panel_pc_manual.pdf` p.33: "Protection rating
Front IP54, rear IP20"
- sources (all): hmi/siemens/unified-comfort-mtp/unified_comfort_panels_operating_instructions.pdf, hmi/beckhoff/cp6000-series/cp6600_panel_pc_manual.pdf

- [x] OK   - [ ] fix: 

## C01 · spec

**Q:** When connecting a Mitsubishi GOT2000 to a KEYENCE PLC over Ethernet, what is the default port No. of the connected Ethernet module in the Connected Ethernet Controller Setting?

**Expected:** The default port No. of the connected KEYENCE Ethernet module is 8501 (set to match the PLC side port No.).

- `hmi/mitsubishi/got2000/got2000_connection_manual_non_mitsubishi_products_1.pdf` p.338: "Port No. Set the port No. of the connected Ethernet module. (Default: 8501)"
- sources (any): hmi/mitsubishi/got2000/got2000_connection_manual_non_mitsubishi_products_1.pdf

- [x] OK   - [ ] fix: 

## C02 · spec

**Q:** How many Mitsubishi GOT2000 units can be connected as DeviceNet slaves to one DeviceNet master?

**Expected:** Up to 63 GOT modules (DeviceNet slave equipment) can be connected to one DeviceNet master equipment.

- `hmi/mitsubishi/got2000/got2000_connection_manual_microcomputer_modbus.pdf` p.241: "Up to 63 GOT modules (DeviceNet slave equipment) can be connected to one DeviceNet master equipment."
- sources (any): hmi/mitsubishi/got2000/got2000_connection_manual_microcomputer_modbus.pdf

- [x] OK   - [ ] fix: 

## C03 · spec

**Q:** What is the maximum power consumption of the Mitsubishi GOT Simple GS2107-WTBD?

**Expected:** The GS2107-WTBD consumes 6.5 W (271 mA/24 V) or less (3.8 W (158 mA/24 V) or less with the backlight off).

- `hmi/mitsubishi/got-simple-gs21/gs25_gs21_user_manual.pdf` p.146: "Power consumption 7.6 W (317 mA/24 V) or less 6.5 W (271 mA/24 V) or less 7.6 W (317 mA/24 V) or less 6.5 W (271 mA/24 V) or less"
- `hmi/mitsubishi/got-simple-gs21/gs21_general_description.pdf` p.1: "GS2110-WTBD GS2107-WTBD Input power supply voltage 24VDC (+10% -15%), ripple voltage 200mV or less Power consumption 7.6W (317mA/24V) or less 6.5W (271mA/24V) or less"
- `hmi/mitsubishi/got-simple-gs21/got_simple_series_catalog.pdf` p.36: "Power consumption 7.6 W (317 mA/24 V) or less 6.5 W (271 mA/24 V) or less"
- sources (any): hmi/mitsubishi/got-simple-gs21/gs25_gs21_user_manual.pdf, hmi/mitsubishi/got-simple-gs21/gs21_general_description.pdf, hmi/mitsubishi/got-simple-gs21/got_simple_series_catalog.pdf

- [x] OK   - [ ] fix: 

## C04 · spec

**Q:** What is the built-in clock precision of the Mitsubishi GT2107-W (GT21 wide model)?

**Expected:** The GT2107-W built-in clock precision is ±45 seconds/month at an ambient temperature of 25 °C.

- `hmi/mitsubishi/got2000/got2000_gt27_gt25_hardware_user_manual.pdf` p.102: "Built-in clock precision ±45 seconds/month (Ambient temperature: 25 °C)"
- `hmi/mitsubishi/got2000/got2000_series_catalog.pdf` p.21: "Built-in clock precision ±45 seconds/month (ambient temperature: 25 °C)"
- sources (any): hmi/mitsubishi/got2000/got2000_gt27_gt25_hardware_user_manual.pdf, hmi/mitsubishi/got2000/got2000_series_catalog.pdf

- [x] OK   - [ ] fix: 

## C05 · spec

**Q:** What does the Omron NB10W-TW01B (non-V1) HMI weigh?

**Expected:** The NB10W-TW01B weighs 1525 g (power consumption 14 W).

- `hmi/omron/nb-series/nb_series_setup_manual.pdf` p.90: "NB10W-TW01B 14W 1525g"
- `hmi/omron/nb-series/nb_series_startup_guide.pdf` p.29: "NB10W-TW01B 14W 1525g"
- sources (any): hmi/omron/nb-series/nb_series_setup_manual.pdf, hmi/omron/nb-series/nb_series_startup_guide.pdf

- [x] OK   - [ ] fix: 

## C06 · spec

**Q:** Which communication protocol does an Omron NA-series HMI use to connect to an OMRON Programmable Multi-Axis Controller (Power PMAC), and what must be entered on the controller side to enable it?

**Expected:** The NA connects via Modbus/TCP (Communication Driver "Modbus/TCP", Device Series "CK3"), and the command Sys.ModbusServerEnable=1 must be entered from the PowerPMAC IDE terminal.

- `hmi/omron/na-series/na_series_device_connection_user_manual.pdf` p.108: "You can connect a NA-series Programmable Terminal to a Programmable Multi-Axis Controller using Modbus/TCP."
- `hmi/omron/na-series/na_series_device_connection_user_manual.pdf` p.109: "The following command must be entered from the PowerPMAC IDE terminal. Sys.ModbusServerEnable=1"
- `hmi/omron/na-series/na_series_device_connection_user_manual.pdf` p.111: "Communication Driver: Select "Modbus/TCP"."
- sources (any): hmi/omron/na-series/na_series_device_connection_user_manual.pdf

- [x] OK   - [ ] fix: 

## C07 · spec

**Q:** What is the ambient operating temperature range of the Omron NSH5 hand-held PT (NSH5-V2)?

**Expected:** The NSH5-V2 hand-held PT is rated for an ambient operating temperature of 0 to 40°C (power consumption 10 W max.).

- `hmi/omron/ns-series/ns_series_datasheet.pdf` p.39: "Power consumption 10 W max. Ambient operating temperature 0 to 40C"
- sources (any): hmi/omron/ns-series/ns_series_datasheet.pdf

- [x] OK   - [ ] fix: 

## C08 · spec

**Q:** In Delta DOPSoft, how many actions can be configured on a single Multiple actions button?

**Expected:** Up to 32 actions can be set for each of press, release and long press, so one Multiple actions button can execute up to 32*3 (96) actions.

- `hmi/delta/dop-100/dopsoft_user_manual.pdf` p.376: "You can set up to 32 actions for each press, release, and long press, so one Multiple actions button can execute up to 32*3 actions."
- sources (any): hmi/delta/dop-100/dopsoft_user_manual.pdf

- [x] OK   - [ ] fix: 

## C09 · spec

**Q:** What is the display resolution of the Delta DOP-110WS 10.1" HMI?

**Expected:** The DOP-110WS has a resolution of 1024 x 600 pixels.

- `hmi/delta/dop-100/dop_100_series_catalog.pdf` p.26: "Resolution (Pixels) 480 x 272 800 x 480 1024 x 600"
- `hmi/delta/dop-100/dop_100_series_selection_guide.pdf` p.28: "Resolution (Pixels) 480 x 272 800 x 480 1,024 x 600"
- sources (any): hmi/delta/dop-100/dop_100_series_catalog.pdf, hmi/delta/dop-100/dop_100_series_selection_guide.pdf

- [x] OK   - [ ] fix: 

## C10 · comparison

**Q:** How does the user memory storage (ROM) capacity of the Mitsubishi GT2712-S compare with that of the GT2512-S?

**Expected:** The GT2712-S (GT27) has 57 MB of storage ROM, whereas the GT2512-S (GT25) has 32 MB, so the GT27 has 25 MB more.

- `hmi/mitsubishi/got2000/got2000_gt27_gt25_hardware_user_manual.pdf` p.70: "Memory for storage (ROM): 57 MB"
- `hmi/mitsubishi/got2000/got2000_gt27_gt25_hardware_user_manual.pdf` p.86: "Memory for storage (ROM): 32 MB"
- `hmi/mitsubishi/got2000/got2000_graphic_operation_catalog.pdf` p.6: "User memory.................. Memory for storage (ROM): 57MB"
- `hmi/mitsubishi/got2000/got2000_graphic_operation_catalog.pdf` p.8: "User memory.................. Memory for storage (ROM): 32MB"
- `hmi/mitsubishi/got2000/got2000_graphic_operation_catalog.pdf` p.43: "Memory for storage (ROM): 57MB"
- `hmi/mitsubishi/got2000/got2000_graphic_operation_catalog.pdf` p.45: "Memory for storage (ROM): 32MB"
- `hmi/mitsubishi/got-simple-gs21/got_simple_series_catalog.pdf` p.30: "Memory for storage (ROM) Other than below: 57 MB GT2705: 32 MB 32 MB"
- sources (all): hmi/mitsubishi/got2000/got2000_gt27_gt25_hardware_user_manual.pdf, hmi/mitsubishi/got2000/got2000_graphic_operation_catalog.pdf, hmi/mitsubishi/got-simple-gs21/got_simple_series_catalog.pdf

- [x] OK   - [ ] fix: 

## C11 · comparison

**Q:** Which draws more power: the Omron NA5-7W or the Delta DOP-107WV 7" HMI, and what are their maximum power consumption figures?

**Expected:** The Omron NA5-7W draws more: 19 W max., versus Max. 8.4 W for the Delta DOP-107WV.

- `hmi/omron/na-series/na5_v2_datasheet.pdf` p.23: "Power consumption 29 W max. 28 W max. 23 W max. 19 W max."
- `hmi/omron/na-series/na5_v1_series_datasheet.pdf` p.30: "Power consumption 29 W max. 25 W max. 23 W max. 19 W max."
- `hmi/omron/na-series/na_series_hardware_v1_user_manual.pdf` p.44: "NA5-7W001S-V1 Silver 7.0 inches 19 W max."
- `hmi/omron/na-series/na_series_hardware_v1_user_manual.pdf` p.46: "29 W max. 25 W max. 23 W max. 19 W max."
- `hmi/omron/na-series/na_series_hardware_v2_user_manual.pdf` p.42: "NA5-7W001S-V2 Silver 7.0 inches 19 W max."
- `hmi/omron/na-series/na_series_hardware_v2_user_manual.pdf` p.44: "Power consumption 29 W max. 28 W max. 23 W max. 19 W max."
- `hmi/delta/dop-100/dop_100_series_catalog.pdf` p.26: "Power Consumption *5 Max. 5.8 W *3 Max. 8.4 W *3 Max. 11 W"
- `hmi/delta/dop-100/dop_100_series_selection_guide.pdf` p.28: "Power Consumption *5 Max. 5.8 W *3 Max. 8.4 W *3 Max. 11 W"
- ⚠ 19 W (NA5-7W) and 8.4 W (DOP-107WV) are column positions in flattened tables; confirm against the PDFs.
- sources (all): hmi/omron/na-series/na5_v2_datasheet.pdf, hmi/omron/na-series/na5_v1_series_datasheet.pdf, hmi/omron/na-series/na_series_hardware_v1_user_manual.pdf, hmi/omron/na-series/na_series_hardware_v2_user_manual.pdf, hmi/delta/dop-100/dop_100_series_catalog.pdf, hmi/delta/dop-100/dop_100_series_selection_guide.pdf

- [x] OK   - [ ] fix: 

## D01 · spec

**Q:** What input voltage range does the Weintek MT8071iP accept?

**Expected:** The MT8071iP accepts a wide input voltage range of 10.5~28VDC (power consumption 1A@12VDC; 500mA@24VDC).

- `hmi/weintek/ip-series/mt8071ip1_datasheet.pdf` p.1: "Input Power 
10.5~28VDC 
Power Consumption 
1A@12VDC ; 500mA@24VDC"
- `hmi/weintek/ip-series/mt8071ip1_datasheet.pdf` p.1: "Wide input voltage range: 10.5~28VDC"
- sources (any): hmi/weintek/ip-series/mt8071ip1_datasheet.pdf

- [x] OK   - [ ] fix: 

## D02 · spec

**Q:** What is the approximate weight of the Weintek cMT2158X 15-inch HMI?

**Expected:** The cMT2158X weighs approx. 2.74 kg.

- `hmi/weintek/cmt-series/cmt2158x_15in_datasheet.pdf` p.1: "Panel Cutout 
352 x 279 mm 
Weight 
Approx. 2.74 kg"
- `hmi/weintek/cmt-series/cmt_series_brochure.pdf` p.12: "Approx. 1.7 kg
Approx. 2.74 kg
Approx. 1.6 kg"
- `hmi/weintek/cmt-x-series/cmt_series_edge_computing_brochure.pdf` p.11: "Approx. 1.2 kg
Approx. 2.74 kg
Approx. 1.6 kg"
- sources (any): hmi/weintek/cmt-series/cmt2158x_15in_datasheet.pdf, hmi/weintek/cmt-series/cmt_series_brochure.pdf, hmi/weintek/cmt-x-series/cmt_series_edge_computing_brochure.pdf

- [x] OK   - [ ] fix: 

## D03 · spec

**Q:** What is the operating temperature range of the Weintek cMT-SVR-200 server?

**Expected:** The cMT-SVR-200 (and cMT-SVR-202) operates from -10° ~ 55°C (14° ~ 131°F).

- `hmi/weintek/cmt-svr/cmt_svr_200_202_datasheet.pdf` p.1: "Operating Temperature 
-10° ~ 55°C (14° ~ 131°F)"
- `hmi/weintek/cmt-series/cmt_series_brochure.pdf` p.17: "-20° ~ 55° C (-4° ~ 131° F)
-10° ~ 55° C (14° ~ 131° F)"
- `hmi/weintek/cmt-x-series/cmt_series_edge_computing_brochure.pdf` p.17: "-20° ~ 55° C (-4° ~ 131° F)
-10° ~ 55° C (14° ~ 131° F)"
- sources (any): hmi/weintek/cmt-svr/cmt_svr_200_202_datasheet.pdf, hmi/weintek/cmt-series/cmt_series_brochure.pdf, hmi/weintek/cmt-x-series/cmt_series_edge_computing_brochure.pdf

- [x] OK   - [ ] fix: 

## D04 · spec

**Q:** What is the input power requirement of the Red Lion Graphite G310C, including maximum wattage?

**Expected:** The G310C requires +24 VDC ±20% at 33 W maximum (a 24 VDC supply rated at 33 W).

- `hmi/red-lion/graphite/g310c_datasheet.pdf` p.2: "G310C: +24 VDC ±20% @ 33 W maximum."
- `hmi/red-lion/graphite/g310c_datasheet.pdf` p.3: "The G310C requires a 24 VDC power supply rated at 33 W"
- sources (any): hmi/red-lion/graphite/g310c_datasheet.pdf

- [x] OK   - [ ] fix: 

## D05 · spec

**Q:** How much does the Red Lion Graphite G315C weigh?

**Expected:** The G315C weighs 11.41 lbs (5.17 Kg).

- `hmi/red-lion/graphite/g315c_datasheet.pdf` p.2: "13. WEIGHT: 11.41 lbs (5.17 Kg)"
- sources (any): hmi/red-lion/graphite/g315c_datasheet.pdf

- [x] OK   - [ ] fix: 

## D06 · spec

**Q:** What is the maximum power consumption of the Schneider Harmony ST6 HMIST6700?

**Expected:** The HMIST6700 has a maximum power consumption of 18.5 W (rated input 24 Vdc).

- `hmi/schneider/harmony-st6/harmony_st6_user_manual.pdf` p.22: "HMIST6600
HMIST6700
Rated input voltage
24 Vdc
Input voltage limits
19.2...28.8 Vdc
Voltage dip/short interruption
immunity
10 ms or less (at rated input voltage)
Power
consumption
Max
18.4 W
18.5 W"
- sources (any): hmi/schneider/harmony-st6/harmony_st6_user_manual.pdf

- [x] OK   - [ ] fix: 

## D07 · spec

**Q:** What panel cutout is required to mount a Pro-face STM-6400WA display module?

**Expected:** The STM-6200WA/STM-6400WA display modules mount in a round hole of diameter 22.5 mm (0.88 in), toleranced 22.5 mm (+0/-0.3 mm).

- `hmi/proface/stm6000/stm6000_series_hardware_manual.pdf` p.22: "Panel cut dimensions
Diameter 22.5 mm (0.88 in)"
- `hmi/proface/stm6000/stm6000_series_hardware_manual.pdf` p.38: "22.5 mm (+0/-0.3 mm)
(0.88 in [+0/-0.01 in])"
- sources (any): hmi/proface/stm6000/stm6000_series_hardware_manual.pdf

- [x] OK   - [ ] fix: 

## D08 · spec

**Q:** What is the power consumption of the Beijer X2 pro 15 B2 at rated voltage?

**Expected:** The X2 pro 15 B2 consumes 31.2 W at rated voltage (+24 VDC).

- `hmi/beijer/x2-pro/x2_pro_15_b2_hardware_manual.pdf` p.15: "Power consumption at
rated voltage
31.2 W"
- `hmi/beijer/x2-series/x2_series_operator_panels_brochure.pdf` p.7: "21.6W
28.8W
31.2W
45.6W"
- sources (any): hmi/beijer/x2-pro/x2_pro_15_b2_hardware_manual.pdf, hmi/beijer/x2-series/x2_series_operator_panels_brochure.pdf

- [x] OK   - [ ] fix: 

## D09 · spec

**Q:** What is the display resolution of the Weintek cMT3072XH?

**Expected:** The cMT3072XH has a 7" IPS display with 1024 x 600 resolution (unlike the cMT3072X, which is 800 x 480).

- `hmi/weintek/cmt-x-series/cmt3072xh_datasheet.pdf` p.1: "Display 
7” IPS 
Resolution 
1024 x 600 
Brightness (cd/m2) 
450"
- `hmi/weintek/cmt-x-series/cmt_series_edge_computing_brochure.pdf` p.7: "7”WVA
7”WVA
Resolution
N/A
N/A
800 x 480
1024 x 600"
- DISTRACTOR (must NOT be cited) `hmi/weintek/cmt-x-series/cmt3072x_datasheet.pdf` p.1: "Display 
7” TFT 
Resolution 
800 x 480 
Brightness (cd/m2) 
400"
- ⚠ Brochure p.7 table is flattened (800 x 480 / 1024 x 600 columns); the datasheet is the authority.
- sources (any): hmi/weintek/cmt-x-series/cmt3072xh_datasheet.pdf, hmi/weintek/cmt-x-series/cmt_series_edge_computing_brochure.pdf

- [x] OK   - [ ] fix: 

## D10 · comparison

**Q:** Compare the operating temperature ranges of the Weintek eMT3070A and eMT3150A.

**Expected:** The eMT3070A operates from -20° ~ 50°C (-4° ~ 122°F), while the eMT3150A operates from 0° ~ 50°C (32° ~ 122°F), so the eMT3070A tolerates colder environments.

- `hmi/weintek/emt-series/emt3070a_7in_datasheet.pdf` p.1: "Operating Temperature 
-20° ~ 50°C (-4° ~ 122°F)"
- `hmi/weintek/emt-series/emt3150a_15in_datasheet.pdf` p.1: "Operating Temperature 
0° ~ 50°C (32° ~ 122°F)"
- sources (all): hmi/weintek/emt-series/emt3070a_7in_datasheet.pdf, hmi/weintek/emt-series/emt3150a_15in_datasheet.pdf

- [x] OK   - [ ] fix: 

## D11 · comparison

**Q:** How do the Red Lion FlexEdge DA50A and DA70A compare in weight?

**Expected:** The DA50A weighs 13 oz (404.3 g), while the DA70A weighs 2 lb 2.5 oz (978.05 g).

- `hmi/red-lion/flexedge/flexedge_da50a_datasheet.pdf` p.3: "Polycarbonate enclosure with IP30 rating.
Weight: 13 oz (404.3 g)"
- `hmi/red-lion/flexedge/flexedge_da70a_datasheet.pdf` p.3: "Metal and plastic enclosure with IP30 rating.
Weight: 2 lb 2.5 oz (978.05 g)"
- sources (all): hmi/red-lion/flexedge/flexedge_da50a_datasheet.pdf, hmi/red-lion/flexedge/flexedge_da70a_datasheet.pdf

- [x] OK   - [ ] fix: 

## D12 · comparison

**Q:** Which has the wider operating temperature range: the Schneider Harmony ST6 HMIST6500 or the Beijer X2 pro 10 B2?

**Expected:** The Beijer X2 pro 10 B2 is wider at -10°C to +60°C; the Harmony ST6 HMIST6500 is rated 0...50 °C (32...122 °F) ambient air temperature.

- `hmi/schneider/harmony-st6/harmony_st6_user_manual.pdf` p.23: "Ambient air temperature
0...50 °C (32...122 °F)"
- `hmi/schneider/harmony-st6/basic_and_web_hmi_panels_catalog.pdf` p.6: "Ambient air temperature 0...50 °C/32...122 °F"
- `hmi/beijer/x2-pro/x2_pro_10_b2_hardware_manual.pdf` p.15: "Operating temperature
-10°C to +60°C"
- `hmi/beijer/x2-series/x2_series_operator_panels_brochure.pdf` p.7: "-10°C to +60°C  
0°C to +50°C"
- sources (all): hmi/schneider/harmony-st6/harmony_st6_user_manual.pdf, hmi/schneider/harmony-st6/basic_and_web_hmi_panels_catalog.pdf, hmi/beijer/x2-pro/x2_pro_10_b2_hardware_manual.pdf, hmi/beijer/x2-series/x2_series_operator_panels_brochure.pdf

- [x] OK   - [ ] fix: 

## E01 · unanswerable

**Q:** What is the MTBF of the Weintek cMT3072X?

**Expected:** The documents do not state an MTBF for the Weintek cMT3072X. The answer should say so and must not borrow an MTBF from another vendor's product.

- absence check: grep -rilE 'MTBF|mean time' hmi/weintek -> 0 files (MTBF appears only in 9 Siemens files)
- sources (none): —

- [x] OK   - [ ] fix: 

## E02 · unanswerable

**Q:** What is the list price of the Allen-Bradley PanelView 5510?

**Expected:** The documents contain no pricing for the PanelView 5510. The answer should say pricing isn't in the library.

- absence check: grep -ilE 'price|USD|€|\$ ?[0-9]' hmi/allen-bradley/panelview-5510/* -> 0 files
- sources (none): —

- [x] OK   - [ ] fix: 

## E03 · unanswerable

**Q:** Which Bluetooth version does the Weintek cMT3162X support?

**Expected:** The documents do not mention Bluetooth for the cMT3162X (or any product). The answer should say this isn't stated rather than invent a version.

- absence check: grep -rilE bluetooth hmi/ -> 0 files; cMT3162X exists (cmt3162x_15in_datasheet)
- sources (none): —

- [x] OK   - [ ] fix: 

## E04 · unanswerable

**Q:** What is the operating temperature range of the Weintek cMT3252X?

**Expected:** There is no cMT3252X in the library, so its operating temperature cannot be answered. The answer should say so and must not substitute a similar model's range.

- absence check: grep -ril cMT3252 hmi/ -> 0 files; similarly named cMT models exist
- sources (none): —

- [x] OK   - [ ] fix: 

## E05 · unanswerable

**Q:** What is the display resolution of the Phoenix Contact BTP 2070W HMI?

**Expected:** The library has no Phoenix Contact HMI documentation (Phoenix Contact appears only as a connectable PLC in connection manuals), so this cannot be answered from the documents.

- absence check: grep -rilE 'BTP ?2070' hmi/ -> 0 files; 'Phoenix Contact' only in connection manuals
- sources (none): —

- [x] OK   - [ ] fix: 

## E06 · unanswerable

**Q:** Which Linux kernel version does the Red Lion Graphite G310 run?

**Expected:** The Red Lion documents do not mention Linux or a kernel version for the Graphite G310. The answer should say this isn't stated.

- absence check: grep -rilE '\blinux\b' hmi/red-lion -> 0 files
- sources (none): —

- [x] OK   - [ ] fix: 

## E07 · library

**Q:** Which HMI vendors are covered in the document library?

**Expected:** 12 vendors: Advantech, Allen-Bradley (Rockwell, incl. ASEM), Beckhoff, Beijer, Delta, Mitsubishi, Omron, Pro-face, Red Lion, Schneider, Siemens and Weintek.

- sources (none): —

- [x] OK   - [ ] fix: 

## E08 · library

**Q:** How many Weintek documents are in the library?

**Expected:** 18 Weintek documents (datasheets, installation guide and brochures across the cMT, cMT-X, eMT, iE, iP, cMT-SVR and gateway series).

- sources (none): —

- [x] OK   - [ ] fix: 

## E09 · library

**Q:** Which documents cover the Mitsubishi GOT2000 series?

**Expected:** 10 documents: got2000_connection_manual_microcomputer_modbus.pdf; got2000_connection_manual_non_mitsubishi_products_1.pdf; got2000_connection_manual_non_mitsubishi_products_2.pdf; got2000_graphic_operation_catalog.pdf; got2000_gt27_gt25_hardware_user_manual.pdf; got2000_gt27_gt25_utility_user_manual.pdf; got2000_series_catalog.pdf; gt21_wide_general_description.pdf; gt25_wide_general_description.pdf; gt27_general_description.pdf.

- sources (none): —

- [x] OK   - [ ] fix: 

## F01 · followup

**Q:** Which replacement battery does it take for the real-time clock?

**Previous turn (replayed as chat history, not another golden entry):**

> **User:** What is the maximum power consumption of the PanelView 800 2711R-T7T?
>
> **Assistant:** The 2711R-T7T draws a maximum of 11 W (0.40 A @ 24V DC).

**Expected:** Use catalog number 2711P-Y2032 (or a manufacturer's equivalent such as the Matsushita or Duracell DL2032 lithium battery).

- `hmi/allen-bradley/panelview-800/panelview_800_user_manual.pdf` p.130: "only replace the battery with 2711P-Y2032 or a manufacturer"
- sources (any): hmi/allen-bradley/panelview-800/panelview_800_user_manual.pdf

- [x] OK   - [ ] fix: 

## F02 · followup

**Q:** What IP rating does its stainless-steel version have?

**Previous turn (replayed as chat history, not another golden entry):**

> **User:** How many Ethernet ports does the PanelView 5510 have?
>
> **Assistant:** Two 10/100Base-T Ethernet ports that support Device Level Ring (DLR).

**Expected:** The PanelView 5510 stainless-steel terminal (2715P-T12WD-BSK) is rated IP69 as classified by UL and tested for IP69K according to ISO 20653.

- `hmi/allen-bradley/panelview-5510/panelview_5510_technical_data.pdf` p.3: "Rated IP69 as Classified by UL. Tested for IP69K according to ISO 20653."
- ⚠ Stainless model ↔ IP69 mapping comes from a flattened table on p.3; confirm against the PDF.
- sources (any): hmi/allen-bradley/panelview-5510/panelview_5510_technical_data.pdf

- [x] OK   - [ ] fix: 

## F03 · followup

**Q:** How does that compare with Delta's 7-inch DOP-107WV?

**Previous turn (replayed as chat history, not another golden entry):**

> **User:** What is the maximum power consumption of the Omron NA5-7W?
>
> **Assistant:** 19 W max.

**Expected:** The Delta DOP-107WV draws Max. 8.4 W, so it uses less than half the NA5-7W's 19 W max.

- `hmi/delta/dop-100/dop_100_series_catalog.pdf` p.26: "Power Consumption *5 Max. 5.8 W *3 Max. 8.4 W *3 Max. 11 W"
- `hmi/delta/dop-100/dop_100_series_selection_guide.pdf` p.28: "Power Consumption *5 Max. 5.8 W *3 Max. 8.4 W *3 Max. 11 W"
- ⚠ DOP-107WV 8.4 W is the middle column of a flattened table; confirm against the PDF.
- sources (any): hmi/delta/dop-100/dop_100_series_catalog.pdf, hmi/delta/dop-100/dop_100_series_selection_guide.pdf

- [x] OK   - [ ] fix: 

## F04 · followup

**Q:** And the DA70A?

**Previous turn (replayed as chat history, not another golden entry):**

> **User:** How much does the Red Lion FlexEdge DA50A weigh?
>
> **Assistant:** 13 oz (404.3 g).

**Expected:** The FlexEdge DA70A weighs 2 lb 2.5 oz (978.05 g).

- `hmi/red-lion/flexedge/flexedge_da70a_datasheet.pdf` p.3: "Metal and plastic enclosure with IP30 rating.
Weight: 2 lb 2.5 oz (978.05 g)"
- sources (any): hmi/red-lion/flexedge/flexedge_da70a_datasheet.pdf

- [x] OK   - [ ] fix: 

## F05 · followup

**Q:** What about the cMT3072X?

**Previous turn (replayed as chat history, not another golden entry):**

> **User:** What is the display resolution of the Weintek cMT3072XH?
>
> **Assistant:** 1024 x 600 (7" IPS).

**Expected:** The Weintek cMT3072X has an 800 x 480 display (7" TFT).

- `hmi/weintek/cmt-x-series/cmt3072x_datasheet.pdf` p.1: "Display 
7” TFT 
Resolution 
800 x 480 
Brightness (cd/m2) 
400"
- DISTRACTOR (must NOT be cited) `hmi/weintek/cmt-x-series/cmt3072xh_datasheet.pdf` p.1: "Display 
7” IPS 
Resolution 
1024 x 600 
Brightness (cd/m2) 
450"
- ⚠ Must cite the cMT3072X sheet, not the cMT3072XH one from the previous turn.
- sources (any): hmi/weintek/cmt-x-series/cmt3072x_datasheet.pdf

- [x] OK   - [ ] fix: 

## A13 · spec

**Q:** What is the operating temperature range of a 19-inch Allen-Bradley PanelView Plus 7 Performance terminal (2711P-T19C22D9P) if it is a Series A unit?

**Expected:** Series A 19-in. terminals are rated 0…50 °C (32…122 °F); Series B 19-in. terminals are rated 0…55 °C (32…131 °F).

- `hmi/allen-bradley/panelview-plus7/panelview_plus7_performance_technical_data.pdf` p.3: "19-in. terminals (Series A) 0…50 °C (32…122 °F)"
- `hmi/allen-bradley/panelview-plus7/panelview_plus7_performance_technical_data.pdf` p.3: "19-in. terminals (Series B) 0…55 °C (32…131 °F)"
- difficulty: distractor
- ⚠ Environmental table splits the 19-in. row by series; all other sizes and the Series B 19-in. are 0…55 °C, so a retriever that lands on the generic line gives the wrong value. ArmorView Plus 7 is also 0…50 °C (another distractor).
- sources (any): hmi/allen-bradley/panelview-plus7/panelview_plus7_performance_technical_data.pdf

- [x] OK   - [ ] fix: 

## A14 · spec

**Q:** What panel cutout dimensions are required for an Allen-Bradley ASEM 6300M 15.6-inch panel monitor (display code 15L, AF/GL/SR bezel)?

**Expected:** Dimension A 389.8 mm (15.31 in.) by Dimension B 239.3 mm (9.42 in.), with all dimensions ±1 mm.

- `hmi/allen-bradley/asem-6300/asem_6300m_user_manual.pdf` p.27: "15.6 15L AF-GL-SR 389.8 (15.31) 239.3 ( 9.42)"
- `hmi/allen-bradley/asem-6300/asem_6300m_user_manual.pdf` p.27: "All dimensions are ± 1 mm (0.04 in.)."
- difficulty: table
- ⚠ Table 16 lists 12 display sizes in consecutive rows; the 15.0-in. 15E row (370.0 x 295.0) sits directly above the 15.6-in. 15L row. Extracted text has a stray space in '( 9.42)'.
- sources (any): hmi/allen-bradley/asem-6300/asem_6300m_user_manual.pdf

- [x] OK   - [ ] fix: 

## A15 · spec

**Q:** Which adapter kit lets you install a 15-inch PanelView Plus 7 Performance touch-screen terminal into the panel cutout of a legacy Allen-Bradley PanelView 1400 or 1400e touch-screen terminal?

**Expected:** Adapter kit 2711P-RAAT15 (the keypad version of the 1400/1400e is replaced via 2711P-RAAK15 with a 15 in. keypad-with-touch terminal). These kits are for Plus 7 Performance terminals only, not Plus 7 Standard.

- `hmi/allen-bradley/panelview-plus7/legacy_panelview_to_plus7_migration_guide.pdf` p.39: "2711P-RAAT15 1400 and 1400e terminals, touch screen 15 in. touch screen"
- `hmi/allen-bradley/panelview-plus7/legacy_panelview_to_plus7_migration_guide.pdf` p.39: "Do not install a PanelView Plus 7 Standard terminal with these adapter kits."
- difficulty: table
- ⚠ Adapter Kit Conversion Table has seven rows; 2711P-RAAK15 (1400 keypad) is the adjacent row and 2711P-RAAT12/-RAAT12K cover the 1000/1000e. Document is 118 pages.
- sources (any): hmi/allen-bradley/panelview-plus7/legacy_panelview_to_plus7_migration_guide.pdf

- [x] OK   - [ ] fix: 

## B12 · spec

**Q:** What is the display luminance (brightness) of the Advantech WebOP-3000T series operator panel WOP-3100T?

**Expected:** The WOP-3100T (10.1" WSVGA) has a luminance of 550 cd/m2 (the sibling WOP-3070T and WOP-3120T are 500 cd/m2).

- `hmi/advantech/webop-3000t/advantech_intelligent_operator_panels_catalog.pdf` p.4: "Luminance 500 cd/m2 550 cd/m2 500 cd/m2"
- difficulty: distractor
- ⚠ Selection-guide table with three model columns (WOP-3070T | WOP-3100T | WOP-3120T); 550 cd/m2 is the middle column. Siblings WOP-3070T and WOP-3120T both have 500 cd/m2.
- sources (any): hmi/advantech/webop-3000t/advantech_intelligent_operator_panels_catalog.pdf

- [x] OK   - [ ] fix: 

## B13 · spec

**Q:** What is the power consumption without loads of the Siemens SIMATIC HMI IM-319A industrial monitor?

**Expected:** The IM-319A draws 21 W without loads (24 W load-dependent); note the larger IM-322A is lower at 18 W without loads.

- `hmi/siemens/industrial-monitors-im/im312a_315a_319a_322a_operating_instructions.pdf` p.52: "Power consumption, without loads 14 W 16 W 21 W 18 W"
- difficulty: distractor
- ⚠ Four-column table (IM-312A | IM-315A | IM-319A | IM-322A); 21 W is the third column. Counter-intuitive sibling: the bigger IM-322A is 18 W, so a retriever picking 'the largest value' or the last column fails. Column header line is a few lines above the value line on the same page.
- sources (any): hmi/siemens/industrial-monitors-im/im312a_315a_319a_322a_operating_instructions.pdf

- [x] OK   - [ ] fix: 

## B14 · spec

**Q:** What is the maximum permitted ambient temperature for a Siemens SIMATIC TP2200 Comfort panel mounted vertically in landscape format?

**Expected:** 0 ... 45 °C for the TP1900 Comfort and TP2200 Comfort (a footnote to the 0 ... 50 °C value that applies to all other Comfort Panels).

- `hmi/siemens/tp-comfort/tp_comfort_panels_hardware_manual.pdf` p.198: "TP1900 Comfort and TP2200 Comfort: 0 ... 45 °C"
- difficulty: long-doc
- ⚠ Footnote-qualified value: the table row 'Vertical 0 ... 50 °C 1' carries footnote 1 which lowers the limit to 45 °C for TP1900/TP2200 only. The hardware manual is >200 pages. The datasheet is a pictorial quick-install sheet whose extracted text is fragmentary; the quote exists but context is weak. The pictorial Comfort Panels datasheet also carries '45 °C (TP1900, TP2200)' but its extracted text is fragmentary, so it is not listed as a source.
- sources (any): hmi/siemens/tp-comfort/tp_comfort_panels_hardware_manual.pdf

- [x] OK   - [ ] fix: 

## C12 · spec

**Q:** What is the maximum apparent power and the maximum-load power consumption of the AC-powered Mitsubishi GT27 model GT2715-XTBA-040?

**Expected:** The GT2715-XTBA-040 (100 to 240 V AC) has a maximum apparent power of 122 VA and consumes 44 W or less under the maximum load (25 W stand-alone, 10 W with backlight off).

- `hmi/mitsubishi/got2000/gt27_general_description.pdf` p.1: "Max. apparent power 122VA 82VA"
- `hmi/mitsubishi/got2000/gt27_general_description.pdf` p.1: "maximum load 44W or less 36W or less 34W or less 33W or less"
- difficulty: table
- ⚠ The -040 models lack the extension interface, so their power figures differ from standard GT27 models in the hardware manual. GT2715 is the first column (122VA/44W); GT2712-STBA-040 etc. share 82VA. The DC GT2715-XTBD-040 is 30 W or less — different model suffix.
- sources (any): hmi/mitsubishi/got2000/gt27_general_description.pdf

- [x] OK   - [ ] fix: 

## C13 · spec

**Q:** When a Delta DOP-100 HMI is connected to a Delta CNC controller using the ASCII protocol, what are the HMI factory-default control area/status area addresses and the default serial settings?

**Expected:** The factory default control area/status area is DT0/DT10, with baud rate 9600, 7 data bits, even parity, 1 stop bit and controller station number 1 (RS-485 connection).

- `hmi/delta/dop-100/dop_100_series_connection_manual.pdf` p.1: "Control Area / Status Area: DT0/DT10"
- `hmi/delta/dop-100/dop_100_series_connection_manual.pdf` p.1: "Baud Rate: 9600. 7. Even. 1"
- difficulty: distractor
- ⚠ Same manual lists Delta AS series PLC (Standard Modbus / Modbus TCP) with control/status area D0/D10 and Modbus TCP port 502 on pages 3 and 5 — easy to confuse with the CNC ASCII entry (DT0/DT10).
- sources (any): hmi/delta/dop-100/dop_100_series_connection_manual.pdf

- [x] OK   - [ ] fix: 

## C14 · spec

**Q:** When a Mitsubishi GOT connects to Siemens SIMATIC S7-300/400/1200/1500 PLCs over Ethernet using OP communication, how many PLCs can one GT21 or GS21 connect to, compared with a GT27/GT25?

**Expected:** For an N:1 (PLC:GOT) OP-communication configuration, a GT21 or GS21 can connect to 4 PLCs or less, whereas GT27, GT25, GT23 and GS25 can connect to 128 or less.

- `hmi/mitsubishi/got2000/got2000_connection_manual_non_mitsubishi_products_2.pdf` p.528: "<For GT27, GT25, GT23, and GS25> 128 or less"
- `hmi/mitsubishi/got2000/got2000_connection_manual_non_mitsubishi_products_2.pdf` p.528: "<For GT21, GS21> 4 or less"
- difficulty: long-doc
- ⚠ ~700-page connection manual. The FETCH/WRITE table on p.526 says '16 PLCs or less for 1 GOT' — a different connection type; the 4/128 split is in the OP-communication table on p.528.
- sources (any): hmi/mitsubishi/got2000/got2000_connection_manual_non_mitsubishi_products_2.pdf

- [x] OK   - [ ] fix: 

## D13 · spec

**Q:** What is the rated power consumption of the Weintek cMT2078X 7-inch HMI?

**Expected:** The cMT2078X consumes 820mA at 24VDC (input power 24±20% VDC).

- `hmi/weintek/cmt-series/cmt2078x_7in_datasheet.pdf` p.1: "Power Consumption 820mA@24VDC"
- difficulty: distractor
- ⚠ Near-identical siblings cMT3072X and cMT3072XH (same 200.3 x 146.3 x 35.0 mm housing) are rated 850mA@24VDC; MT8071iE1 is 450mA@24VDC. Check the answer is 820 mA, not 850.
- sources (any): hmi/weintek/cmt-series/cmt2078x_7in_datasheet.pdf

- [x] OK   - [ ] fix: 

## D14 · spec

**Q:** At what maximum ambient temperature can a Red Lion CR3000 15-inch HMI operate when the cellular modem module is fitted?

**Expected:** With the Cellular Modem Module (CRM000CMCMOD0000) or equivalent fitted, the CR3000 15" is limited to -10 to 45 °C, instead of the normal -10 to 50 °C operating range.

- `hmi/red-lion/cr-series/cr3000_series_user_manual.pdf` p.2: "CR3000 15": Max operating temperature -10 to 45 °C when using Cellular Modem Module (CRM000CMCMOD0000) or equivalent."
- difficulty: distractor
- ⚠ The general line immediately above says -10 to 50 °C, and the CR1000/CR3000 datasheet also gives -10°C to 50°C with no modem qualifier; the answer must give the 45 °C qualified figure.
- sources (any): hmi/red-lion/cr-series/cr3000_series_user_manual.pdf

- [x] OK   - [ ] fix: 

## D15 · spec

**Q:** How much does the Schneider Harmony GTO HMIGTO5315 stainless-steel 10.4-inch panel weigh?

**Expected:** The HMIGTO5315 weighs 2.500 kg (the standard HMIGTO5310 weighs 2.000 kg).

- `hmi/schneider/harmony-gto/harmony_gto_catalog.pdf` p.15: "HMIGTO5315 2.500"
- difficulty: distractor
- ⚠ Flattened references table; the reference and weight (kg) are the last two cells of each row. Sibling HMIGTO5310 (standard version) is 2.000 kg and HMIGTO6315 is 3.000 kg, HMIGTO6310 2.500 kg - make sure the 2.500 is tied to HMIGTO5315.
- sources (any): hmi/schneider/harmony-gto/harmony_gto_catalog.pdf

- [x] OK   - [ ] fix: 

## A16 · comparison

**Q:** Which draws more power at maximum: the Allen-Bradley PanelView 5510 stainless-steel 15-inch terminal 2715P-T15CD-BSK or the PanelView Plus 7 Performance stainless-steel 15-inch terminal 2711P-T15C22D9P-BSHK (Series C)?

**Expected:** The PanelView Plus 7 Performance 2711P-T15C22D9P-BSHK Series C is rated 39 W max, higher than the PanelView 5510 2715P-T15CD-BSK at 33 W.

- `hmi/allen-bradley/panelview-5510/panelview_5510_stainless_steel_technical_data.pdf` p.2: "2715P-T15CD-BSK 33 W"
- `hmi/allen-bradley/panelview-plus7/panelview_plus7_performance_technical_data.pdf` p.8: "(Series C) 39 W max"
- difficulty: table
- ⚠ Plus 7 Perf stainless table p.8 flattens four columns: the Series B 15-in. value is 50 W max, and '(Series C) 33 W max' (12.1-in.) appears immediately before '(Series C) 39 W max' (15-in.). 5510 stainless value is in a four-row table (24/25/26/33 W).
- sources (all): hmi/allen-bradley/panelview-5510/panelview_5510_stainless_steel_technical_data.pdf, hmi/allen-bradley/panelview-plus7/panelview_plus7_performance_technical_data.pdf

- [x] OK   - [ ] fix: 

## A17 · comparison

**Q:** Which is heavier: the Allen-Bradley PanelView Plus 7 Standard 12-inch touch terminal 2711P-T12W21D8S or the PanelView Plus 7 Performance 12.1-inch touch terminal 2711P-T12W22D9P?

**Expected:** The Plus 7 Performance 2711P-T12W22D9P weighs approx. 2.54 kg (5.60 lb), more than the Plus 7 Standard 2711P-T12W21D8S at approx. 1.95 kg (4.29 lb).

- `hmi/allen-bradley/panelview-plus7/panelview_plus7_standard_technical_data.pdf` p.6: "Weight, approx. 1.95 kg (4.29 lb) 3.07 kg (6.75 lb)"
- `hmi/allen-bradley/panelview-plus7/panelview_plus7_performance_technical_data.pdf` p.6: "Weight, approx 2.28 kg (5.03 lb) 2.58 kg (5.69 lb) 2.54 kg (5.60 lb)"
- difficulty: table
- ⚠ Standard TD p.6: 1.95 kg is the first of two columns (12-in., 15-in.). Performance TD p.6: 2.54 kg is the third of three columns (10.4 touch 2.28, 10.4 keypad 2.58, 12.1 touch 2.54).
- sources (all): hmi/allen-bradley/panelview-plus7/panelview_plus7_standard_technical_data.pdf, hmi/allen-bradley/panelview-plus7/panelview_plus7_performance_technical_data.pdf

- [x] OK   - [ ] fix: 

## B15 · comparison

**Q:** Which draws more power: the Advantech WOP-3070T 7-inch operator panel or the Siemens SIMATIC KTP700 Basic (2nd generation)?

**Expected:** The Advantech WOP-3070T draws more: 7 W versus 5.5 W for the Siemens KTP700 Basic (both 24 V DC).

- `hmi/advantech/webop-3000t/advantech_intelligent_operator_panels_catalog.pdf` p.4: "Power Consumption 7W 9W 12W"
- `hmi/siemens/ktp-basic/ktp_basic_panels_2nd_gen_hardware.pdf` p.117: "Power consumption 1 3 W 5.5 W 5.5 W"
- difficulty: table
- ⚠ Both values are first/second columns of flattened multi-model tables: Advantech 7W is the WOP-3070T column (9W = 3100T, 12W = 3120T); Siemens 5.5 W is the KTP700 Basic column (3 W = KTP400 Basic, 5.5 W = KTP700 Basic DP too). The Siemens '1' after 'Power consumption' is a footnote marker.
- sources (all): hmi/advantech/webop-3000t/advantech_intelligent_operator_panels_catalog.pdf, hmi/siemens/ktp-basic/ktp_basic_panels_2nd_gen_hardware.pdf

- [x] OK   - [ ] fix: 

## B16 · comparison

**Q:** How does the front degree of protection of the Siemens TP700 Comfort Outdoor compare with that of the standard TP700 Comfort panel?

**Expected:** The TP700 Comfort Outdoor front is rated IP66 (Type 4X/Type 12 indoor/outdoor) when mounted, one step higher than the standard TP700 Comfort front, which is IP65 according to IEC 60529 (Type 4X/Type 12 indoor use only). Both have IP20 at the rear.

- `hmi/siemens/tp-comfort/tp_comfort_outdoor_panels_manual.pdf` p.28: "When mounted: • IP66"
- `hmi/siemens/tp-comfort/tp_comfort_panels_hardware_manual.pdf` p.200: "IP65 according to IEC 60529"
- difficulty: long-doc
- ⚠ Near-identical product names (TP700 Comfort vs TP700 Comfort Outdoor) make this a strong distractor case; the Outdoor compact manual explicitly takes precedence over the standard Comfort Panels manual. Hardware manual is >200 pages.
- sources (all): hmi/siemens/tp-comfort/tp_comfort_outdoor_panels_manual.pdf, hmi/siemens/tp-comfort/tp_comfort_panels_hardware_manual.pdf

- [x] OK   - [ ] fix: 

## C15 · comparison

**Q:** Which draws more power at maximum: the Omron NA5-12W (V2) HMI or the Mitsubishi GOT2000 GT2512-WXTBD, and what are the figures?

**Expected:** The Omron NA5-12W-V2 draws more: 28 W max., versus 20 W or less under the maximum load for the Mitsubishi GT2512-WXTBD.

- `hmi/omron/na-series/na_series_hardware_v2_user_manual.pdf` p.44: "Power consumption 29 W max. 28 W max. 23 W max. 19 W max."
- `hmi/mitsubishi/got2000/gt25_wide_general_description.pdf` p.1: "maximum load 20 W or less 16 W or less"
- difficulty: distractor
- ⚠ Cross-vendor. NA5-12W is the second column (28 W) between NA5-15W (29 W) and NA5-9W (23 W); the older NA5-12W-V1 is 25 W max. in the V1 manual. GT2512-WX is the 20 W column; GT2510/GT2507 are 16 W.
- sources (all): hmi/omron/na-series/na_series_hardware_v2_user_manual.pdf, hmi/mitsubishi/got2000/gt25_wide_general_description.pdf

- [x] OK   - [ ] fix: 

## C16 · comparison

**Q:** Did the maximum power consumption of the Omron NA5-12W change between the V1 and V2 hardware versions? Give both values.

**Expected:** Yes: the NA5-12W-V1 is rated 25 W max., while the NA5-12W-V2 is rated 28 W max., so the V2 draws 3 W more (the 15W, 9W and 7W models are unchanged at 29, 23 and 19 W).

- `hmi/omron/na-series/na_series_hardware_v1_user_manual.pdf` p.44: "12.1 inches 25 W max. 2.4 kg max."
- `hmi/omron/na-series/na_series_hardware_v2_user_manual.pdf` p.44: "Power consumption 29 W max. 28 W max. 23 W max. 19 W max."
- difficulty: distractor
- ⚠ Same model family, two manuals, same page number (44) in each. V2 value must be read as the 2nd of 4 columns; V1 value appears in the model list (p.44) and again in the general specs (p.46).
- sources (all): hmi/omron/na-series/na_series_hardware_v1_user_manual.pdf, hmi/omron/na-series/na_series_hardware_v2_user_manual.pdf

- [x] OK   - [ ] fix: 

## D16 · comparison

**Q:** Which 15-inch HMI is heavier: the Red Lion Graphite G15 or the Weintek cMT3152X?

**Expected:** The Red Lion Graphite G15 is heavier at 7.73 lb (3.50 kg), versus approx. 2.85 kg for the Weintek cMT3152X.

- `hmi/red-lion/graphite/graphite_series_full_datasheet.pdf` p.2: "G15 – 7.73 lb. (3.50 kg)"
- `hmi/weintek/cmt-series/cmt3152x_15in_datasheet.pdf` p.1: "Weight Approx. 2.85 kg"
- difficulty: distractor
- ⚠ Cross-vendor. The Graphite weight is also in graphite_hmi_datasheet.pdf; the G315C datasheet (older Graphite G3) gives 11.41 lbs and cMT3162X is 1.6 kg / cMT2158X 2.74 kg - confirm the right pair is used.
- sources (all): hmi/red-lion/graphite/graphite_series_full_datasheet.pdf, hmi/weintek/cmt-series/cmt3152x_15in_datasheet.pdf

- [x] OK   - [ ] fix: 

## D17 · comparison

**Q:** What front-panel ingress protection do the Weintek eMT3105P and eMT3070A have, and which is rated higher?

**Expected:** The eMT3070A has a NEMA4 / IP66 compliant front panel, while the eMT3105P is only NEMA4 / IP65 compliant, so the eMT3070A is rated higher.

- `hmi/weintek/emt-series/emt3105p_10in_datasheet.pdf` p.1: "NEMA4 / IP65 Compliant Front Panel"
- `hmi/weintek/emt-series/emt3070a_7in_datasheet.pdf` p.1: "NEMA4 / IP66 Compliant Front Panel"
- difficulty: distractor
- ⚠ Same eMT family, one digit difference (IP65 vs IP66). The eMT3150A sibling is also in the corpus; the brochure text may claim IP66 for the family generally.
- sources (all): hmi/weintek/emt-series/emt3105p_10in_datasheet.pdf, hmi/weintek/emt-series/emt3070a_7in_datasheet.pdf

- [x] OK   - [ ] fix: 

## E10 · unanswerable

**Q:** What is the power consumption of the Siemens SIMATIC KTP1500 Basic panel?

**Expected:** There is no KTP1500 Basic in the documents; the Basic Panels 2nd Generation range is KTP400/700/900/1200. The answer should say the model is not found and must not return the KTP1200 Basic figure as if it were the KTP1500's.

- absence check: grep -rlE 'KTP ?1500' hmi/ -> 0 files; KTP1200 appears in 1 file (ktp_basic_panels_2nd_gen_hardware) and is asked in B01
- difficulty: distractor
- ⚠ Near-miss trap: the sibling KTP1200 Basic exists with a real power figure (B01). A wrong answer here is one that silently substitutes the KTP1200 value.
- sources (none): —

- [x] OK   - [ ] fix: 

## E11 · unanswerable

**Q:** What SIL (Safety Integrity Level) is the Beijer X2 pro 10 B2 certified to?

**Expected:** The Beijer documents do not state any SIL rating for the X2 pro 10 B2. The answer should say so and must not borrow a SIL figure from another vendor's document.

- absence check: grep -rlE '\bSIL\b' hmi/beijer -> 0 files; 'SIL' appears in 5 files from other vendors (ASEM 6300, GOT2000, Siemens IFP/IM)
- difficulty: distractor
- ⚠ Cross-vendor trap: SIL text exists in Siemens/Mitsubishi/ASEM documents and could be retrieved for a 'safety' query. The product itself exists (x2_pro_10_b2_hardware_manual).
- sources (none): —

- [x] OK   - [ ] fix: 

## E12 · unanswerable

**Q:** Does the Schneider Harmony ST6 HMIST6700 support Power over Ethernet (PoE)?

**Expected:** The documents do not mention Power over Ethernet for any Harmony ST6 model (or any HMI in the library). The answer should say the documents do not state PoE support rather than asserting yes or no.

- absence check: grep -rliE '\bPoE\b|power over ethernet' hmi/ -> 0 files; HMIST6700 exists (harmony_st6_user_manual, basic_and_web_hmi_panels_catalog) and D06 asks its power consumption
- difficulty: distractor
- ⚠ Yes/no trap: the ST6 manual has Ethernet-interface and 24 V power sections that an LLM may combine into an invented 'no PoE' or 'yes' answer; the correct behaviour is to say it is not stated.
- sources (none): —

- [x] OK   - [ ] fix: 

## E13 · unanswerable

**Q:** Does the Beckhoff CP6600 panel PC have built-in Wi-Fi?

**Expected:** The Beckhoff documents do not mention Wi-Fi, WLAN or any wireless interface for the CP6600 (or any Beckhoff panel in the library). The answer should say this is not stated, not infer an answer from the wired-interface list.

- absence check: grep -rliE 'wi-?fi|wlan|wireless' hmi/beckhoff -> 0 files (wireless terms appear in 28 files from 9 other vendors); CP6600 exists (cp6600_panel_pc_manual, asked in B11)
- difficulty: distractor
- ⚠ Cross-vendor + yes/no trap: Weintek/Mitsubishi/Red Lion documents discuss Wi-Fi and may be retrieved; the CP6600 manual lists only wired interfaces.
- sources (none): —

- [x] OK   - [ ] fix: 

## G01 · multihop

**Q:** Which of these Allen-Bradley small-format (6.5 to 7 in.) terminals has the highest display resolution: the PanelView 800 2711R-T7T, the PanelView Plus 7 Standard 2711P-T7C21D8S, or the PanelView 5510 2715P-T7CD?

**Expected:** The PanelView 800 2711R-T7T at 800 x 480 (WVGA). Both the Plus 7 Standard 2711P-T7C21D8S (6.5 in.) and the PanelView 5510 2715P-T7CD (6.5 in.) are 640 x 480 VGA.

- `hmi/allen-bradley/panelview-800/panelview_800_technical_data.pdf` p.5: "Resolution (pixels) 480 x 272 800 x 480 800 x 600"
- `hmi/allen-bradley/panelview-plus7/panelview_plus7_standard_technical_data.pdf` p.5: "640 x 480 VGA, 18-bit color graphics 800 x 480 WVGA, 18-bit color graphics"
- `hmi/allen-bradley/panelview-5510/panelview_5510_technical_data.pdf` p.4: "Display resolution/aspect ratio 640 x 480 VGA/4:3 800 x 480 WVGA/5:3"
- difficulty: table
- ⚠ The Plus 7 Standard 2711P-T7C21D8S and the 5510 2715P-T7CD are 6.5 in. displays despite the '7' in the catalog number. Each value is a column pick: PV800 TD p.5 columns are T4T/T7T/T10T (800 x 480 is the middle one); Std TD p.5 columns 7-in/9-in/10-in; 5510 TD p.4 the 7 in. wide 2715P-T7WD is 800 x 480 but the asked 2715P-T7CD (6.5 in.) is 640 x 480.
- sources (all): hmi/allen-bradley/panelview-800/panelview_800_technical_data.pdf, hmi/allen-bradley/panelview-plus7/panelview_plus7_standard_technical_data.pdf, hmi/allen-bradley/panelview-5510/panelview_5510_technical_data.pdf

- [x] OK   - [ ] fix: 

## G02 · multihop

**Q:** What is the primary PanelView Plus 7 replacement for a legacy Allen-Bradley PanelView Standard 550 terminal 2711-K5A1, and how much does that replacement terminal weigh?

**Expected:** The primary replacement is the PanelView Plus 7 Standard 6-in. touch terminal 2711P-T6C21D8S (cutout 123 x 156 mm, 640 x 480, one Ethernet port); it weighs approximately 0.70 kg (1.53 lb).

- `hmi/allen-bradley/panelview-plus7/legacy_panelview_to_plus7_migration_guide.pdf` p.21: "2711P-T6C21D8S 123 (4.84) 156 (6.14) 640 x 480"
- `hmi/allen-bradley/panelview-plus7/panelview_plus7_standard_technical_data.pdf` p.4: "Weight, approx 0.44 kg (0.97 lb) 0.70 kg (1.53 lb)"
- difficulty: long-doc
- ⚠ Hop 1 is the 550 Primary Replacement table in the 118-page migration guide (row 2711-K5A1 -> 2711P-T6C21D8S); hop 2 is the Standard TD p.4 weight row where 0.70 kg is the second column (4-in. is 0.44 kg).
- sources (all): hmi/allen-bradley/panelview-plus7/legacy_panelview_to_plus7_migration_guide.pdf, hmi/allen-bradley/panelview-plus7/panelview_plus7_standard_technical_data.pdf

- [x] OK   - [ ] fix: 

## G03 · multihop

**Q:** Which of the Beckhoff CP37xx panel PC, CP6700 panel PC and CP39xx-0000 multi-touch control panel may be operated at an ambient temperature of 55 °C?

**Expected:** Only the CP39xx-0000 control panel (operation 0 °C ... +55 °C). The CP37xx is limited to 0 °C to +45 °C and the CP6700 to 0 °C ... +50 °C.

- `hmi/beckhoff/cp3xxx-series/cp37xx_panel_pc_manual.pdf` p.47: "Operation: 0 °C to +45 °C"
- `hmi/beckhoff/cp6000-series/cp6700_panel_pc.pdf` p.40: "Operation: 0 °C ... +50 °C"
- `hmi/beckhoff/cp3xxx-series/cp39xx_multitouch_control_panel_manual.pdf` p.45: "Operation: 0 °C ... +55 °C"
- difficulty: distractor
- ⚠ Three documents with identically-worded 'Permissible ambient temperature' rows but different limits. Extra trap: the CP39xx-0010 variant (p46 of the same manual) is only 0 ... +50 °C, and the CP6600 (separate manual) is 0 ... +55 °C — the question deliberately names CP6700, not CP6600.
- sources (all): hmi/beckhoff/cp3xxx-series/cp37xx_panel_pc_manual.pdf, hmi/beckhoff/cp6000-series/cp6700_panel_pc.pdf, hmi/beckhoff/cp3xxx-series/cp39xx_multitouch_control_panel_manual.pdf

- [x] OK   - [ ] fix: 

## G04 · multihop

**Q:** Which of these HMI fronts are rated IP66 rather than IP65: Advantech WOP-3070T, Siemens TP700 Comfort Outdoor, Siemens TP700 Comfort (standard), Beckhoff CP3907?

**Expected:** The Advantech WOP-3070T (IP66-rated front panel) and the Siemens TP700 Comfort Outdoor (front IP66 when mounted) are IP66; the standard Siemens TP700 Comfort front is IP65 according to IEC 60529 and the Beckhoff CP3907 (CP39xx) is IP65.

- `hmi/advantech/webop-3000t/advantech_intelligent_operator_panels_catalog.pdf` p.4: "IP66-rated front panel"
- `hmi/siemens/tp-comfort/tp_comfort_outdoor_panels_manual.pdf` p.28: "When mounted: • IP66"
- `hmi/siemens/tp-comfort/tp_comfort_panels_hardware_manual.pdf` p.200: "IP65 according to IEC 60529"
- `hmi/beckhoff/cp3xxx-series/cp39xx_multitouch_control_panel_manual.pdf` p.45: "Protection rating IP65"
- difficulty: distractor
- ⚠ Four documents, three vendors. 'IP66-rated front panel' appears in all three WOP-3000T columns on the Advantech page (same value, so column position does not matter). TP700 Comfort vs TP700 Comfort Outdoor is the sibling trap; the Beckhoff IP65 is 'all-round', not front-only.
- sources (all): hmi/advantech/webop-3000t/advantech_intelligent_operator_panels_catalog.pdf, hmi/siemens/tp-comfort/tp_comfort_outdoor_panels_manual.pdf, hmi/siemens/tp-comfort/tp_comfort_panels_hardware_manual.pdf, hmi/beckhoff/cp3xxx-series/cp39xx_multitouch_control_panel_manual.pdf

- [x] OK   - [ ] fix: 

## G05 · multihop

**Q:** Of the three Mitsubishi 7-inch wide panels GT2107-WTBD, GS2107-WTBD and GT2507-WTBD, which consume more than 10 W under the maximum load? Give each value.

**Expected:** GT2107-WTBD (11.3 W or less) and GT2507-WTBD (16 W or less) exceed 10 W; the GS2107-WTBD does not, at 6.5 W (271 mA/24 V) or less.

- `hmi/mitsubishi/got2000/gt21_wide_general_description.pdf` p.1: "Under the maximum load 11.3 W or less"
- `hmi/mitsubishi/got-simple-gs21/gs21_general_description.pdf` p.1: "6.5W (271mA/24V) or less"
- `hmi/mitsubishi/got2000/got2000_gt27_gt25_hardware_user_manual.pdf` p.113: "Under the maximum load 20 W or less 16 W or less 16 W or less"
- difficulty: distractor
- ⚠ Needs three documents. GS21 row is 'GS2110-WTBD 7.6W / GS2107-WTBD 6.5W' flattened; GT2507 value is the 3rd column of the GT25-wide row in the hardware manual (GT25 wide general description p.1 also gives 16 W).
- sources (all): hmi/mitsubishi/got2000/gt21_wide_general_description.pdf, hmi/mitsubishi/got-simple-gs21/gs21_general_description.pdf, hmi/mitsubishi/got2000/got2000_gt27_gt25_hardware_user_manual.pdf

- [x] OK   - [ ] fix: 

## G06 · multihop

**Q:** In Delta DOPSoft, what is the default password offered when creating an Auto Update Data File with protection enabled, and if both a USB disk and an SD card contain an HMI_AutoUP folder, which one does the DOP-100 HMI update from first?

**Expected:** The default copy-protection password is 12345678, and the HMI updates from the USB Disk first and then from the SD Card.

- `hmi/delta/dop-100/dopsoft_user_manual.pdf` p.56: "The default is 12345678, as shown in Figure 2.2.1.7.1."
- `hmi/delta/dop-100/dopsoft_user_manual.pdf` p.57: "the HMI first updates the USB Disk and then the SD Card."
- difficulty: long-doc
- ⚠ 1803-page manual; the two facts are on consecutive pages of section 2.2.1.7. 'Create Screen Data File' (2.2.1.6) is a sibling function without the auto-update prompt.
- sources (any): hmi/delta/dop-100/dopsoft_user_manual.pdf

- [x] OK   - [ ] fix: 

## G07 · multihop

**Q:** Which of the Weintek 15-inch cMT models cMT2158X, cMT3152X and cMT3162X have an SD card slot?

**Expected:** The cMT2158X and cMT3152X both have an SD card slot supporting SD/SDHC cards; the cMT3162X has no SD card slot (N/A).

- `hmi/weintek/cmt-series/cmt2158x_15in_datasheet.pdf` p.1: "SD Card Slot SD/SDHC"
- `hmi/weintek/cmt-series/cmt3152x_15in_datasheet.pdf` p.1: "SD Card Slot SD/SDHC"
- `hmi/weintek/cmt-series/cmt3162x_15in_datasheet.pdf` p.1: "SD Card Slot N/A"
- difficulty: distractor
- ⚠ Needs the I/O Port row from three sibling datasheets. Many other Weintek datasheets contain 'SD Card Slot N/A' (cMT2078X, cMT3072X, cMT3092X, cMT3103, MT8071iE1), so retrieval could cite the wrong model.
- sources (all): hmi/weintek/cmt-series/cmt2158x_15in_datasheet.pdf, hmi/weintek/cmt-series/cmt3152x_15in_datasheet.pdf, hmi/weintek/cmt-series/cmt3162x_15in_datasheet.pdf

- [x] OK   - [ ] fix: 

## G08 · multihop

**Q:** Which Schneider Harmony GTO panel models cannot be expanded with an SD card?

**Expected:** The HMIGTO1300, HMIGTO1310 and HMIGTO2300 have no SD card interface; all other GTO models (HMIGTO2310, 3510, 4310, 5310, 6310 and the 2315/5315/6315 stainless versions) accept the 4 GB SD card HMIZSD4G.

- `hmi/schneider/harmony-gto/harmony_gto_catalog.pdf` p.15: "96 MB No 1 COM 1 1 HMIGTO1310 0.400"
- `hmi/schneider/harmony-gto/hmigto5310_manual.pdf` p.18: "The HMIGTO1300/1310 and HMIGTO2300 do not have a SD card interface."
- difficulty: long-doc
- ⚠ Catalog p15 'Memory expansion by SD card' column reads No for HMIGTO1300, HMIGTO1310 and HMIGTO2300 and 'Yes (2)' for the rest; the manual footnote *7 (p18 of a 138-page manual) states it directly. Catalog p5 also says 'By 4 GB SD card (except HMIGTO2300)' for the 5.7" column.
- sources (all): hmi/schneider/harmony-gto/harmony_gto_catalog.pdf, hmi/schneider/harmony-gto/hmigto5310_manual.pdf

- [x] OK   - [ ] fix: 

## H01 · procedure

**Q:** How do you replace the real-time clock battery in an Allen-Bradley PanelView Plus 7 Standard terminal (e.g. 2711P-T10C21D8S)?

**Expected:** 1) Disconnect power from the terminal. 2) Remove the battery cover by rotating it from C (closed) to O (open). 3) Press the vertical center tab on the metal latch away from the battery to release it. 4) Insert the new battery (2711P-RY2032 / CR2032) at an angle under the metal latch with the + side up. 5) Gently press down on the opposite side until it locks into place. 6) Replace the cover and rotate it from O (open) to C (closed).

- `hmi/allen-bradley/panelview-plus7/panelview_plus7_standard_user_manual.pdf` p.125: "Remove the battery cover by rotating it from the C (closed) to the O (open) position."
- `hmi/allen-bradley/panelview-plus7/panelview_plus7_standard_user_manual.pdf` p.126: "Insert the new battery at an angle under the metal latch, with the positive polarity (+) up."
- difficulty: long-doc
- ⚠ 156-page manual; steps 1-2 on p.125, steps 3-6 on p.126. Existing A02 covers the PanelView 800 battery part number, not this procedure.
- sources (any): hmi/allen-bradley/panelview-plus7/panelview_plus7_standard_user_manual.pdf

- [x] OK   - [ ] fix: 

## H02 · procedure

**Q:** What are the steps to mount an Allen-Bradley PanelView 5510 stainless-steel terminal (e.g. 2715P-T12WD-BSK) in a panel, and what torque is applied to the mounting clips?

**Expected:** 1) Cut the panel opening using the shipped cutout template (or the user-manual dimensions). 2) Place the terminal screen-down on a clean, flat surface. 3) Position the gasket on the bezel with the alignment plugs facing the bezel alignment features and 4) press each plug into place (compression seal, no sealing compounds). 5) Place the terminal in the cutout. 6) Position the backing plate over the terminal. 7) Slide the mounting clips into the slots. 8) Hand-tighten the clip screws until the backing plate contacts the panel uniformly. 9) Torque the clip screws to 2.3…2.6 N•m (20…23 lb•in) in the specified sequence, 10) repeating until all clips are at torque.

- `hmi/allen-bradley/panelview-5510/panelview_5510_stainless_steel_technical_data.pdf` p.3: "Cut an opening in the panel by using the panel cutout template that is shipped with the terminal"
- `hmi/allen-bradley/panelview-5510/panelview_5510_stainless_steel_technical_data.pdf` p.3: "Torque the mounting clip screws to 2.3…2.6 N•m (20…23 lb•in) by using the specified sequence."
- difficulty: easy
- ⚠ All 10 steps on p.3 of the 4-page product-information sheet; the clip counts (8/8/10/12 for 9/10/12.1/15-in.) appear in the torque-sequence drawings on the same page. Power-wiring screw torque 0.4…0.5 N•m on the same page is a potential confusion.
- sources (any): hmi/allen-bradley/panelview-5510/panelview_5510_stainless_steel_technical_data.pdf

- [x] OK   - [ ] fix: 

## H03 · procedure

**Q:** How is the mounting arm tube fitted to the mounting arm adapter of a Beckhoff CP39xx control panel, and what torques are specified?

**Expected:** 1. Unscrew the hexagon socket screw a few turns with a 3 mm Allen key. 2. Push the panel's connecting cables through the mounting arm tube. 3. Insert the tube 50.2 mm into the adapter up to the stop. 4. Retighten the hexagon socket screw to 3 Nm. 5. Tighten the adapter's slotted nut clockwise with a size 58-62 hook wrench (C9900-Z263) to 20 Nm. (Adapters fit Rittal/Rolec 48 mm tubes.)

- `hmi/beckhoff/cp3xxx-series/cp39xx_multitouch_control_panel_manual.pdf` p.30: "1. Unscrew the hexagon socket screw (1) a few turns with a 3 mm Allen key (section A)."
- `hmi/beckhoff/cp3xxx-series/cp39xx_multitouch_control_panel_manual.pdf` p.30: "3. Insert the mounting arm tube 50.2 mm into the mounting arm adapter to the stop (section B)."
- difficulty: easy
- ⚠ Section 4.2.2 'Mounting arm tube installation'. Two different torques on the same page (3 Nm screw, 20 Nm slotted nut) — check the answer does not swap them. The CP37xx panel PC manual has a near-identical procedure, so retrieval may land there.
- sources (any): hmi/beckhoff/cp3xxx-series/cp39xx_multitouch_control_panel_manual.pdf

- [x] OK   - [ ] fix: 

## H04 · procedure

**Q:** Using the SIMATIC IPC Panel Drivers and Tools (PDT) UPDD Console, how do you perform the extended 25-point touch calibration on a SIMATIC IFP V2 with resistive single-touch screen?

**Expected:** 1. Open the "UPDD Console" dialog. 2. Select the touch controller of the device in the dialog header. 3. Click the "Calibration" tab. 4. Deactivate "Use eeprom storage". 5. Enter "25" under "Number of points". 6. Click "Calibrate" (calibration screen appears on the selected display). 7. Touch the selections one after the other (each confirmed with a check mark). 8. Confirm all prompts until the whole screen is calibrated. 9. Press "Confirm" at the final prompt. Unlike the 3-point calibration, the data is stored in the OS on the PC, not in the device EEPROM.

- `hmi/siemens/ifp-v2/ipc_ifp_panel_driver_tool_user_manual.pdf` p.46: "4. Deactivate the option "Use eeprom storage"."
- `hmi/siemens/ifp-v2/ipc_ifp_panel_driver_tool_user_manual.pdf` p.46: "5. Enter the value "25" under "Number of points"."
- difficulty: distractor
- ⚠ Section 4.8.3.2 'Extended calibration'. The 'Standard calibration' procedure (p45-46) is nearly identical but ACTIVATES 'Use eeprom storage' and uses 3 points — answer must not mix the two. Introductory sentence about EEPROM vs OS storage is on p45.
- sources (any): hmi/siemens/ifp-v2/ipc_ifp_panel_driver_tool_user_manual.pdf

- [x] OK   - [ ] fix: 

## H05 · procedure

**Q:** What is the procedure for installing the BootOS or system application on a Mitsubishi GOT2000 (GT27/GT25) from an SD card using the utility?

**Expected:** 1. Insert the SD card holding the BootOS/system application/project data into the GOT's SD card interface. 2. Close the SD card interface cover. 3. Open the data control function screen in the utility and install the BootOS/system application from the SD card. 4. The SD card access LED stays lit during installation - do not remove the card or open the cover. 5. The GOT restarts automatically when installation completes. 6. After a normal restart, confirm the access LED is off and remove the SD card.

- `hmi/mitsubishi/got2000/got2000_gt27_gt25_utility_user_manual.pdf` p.398: "Install the SD card where the BootOS, system application or project data is stored in the SD card interface of the GOT."
- `hmi/mitsubishi/got2000/got2000_gt27_gt25_utility_user_manual.pdf` p.398: "GOT restarts automatically after installation is completed."
- difficulty: long-doc
- ⚠ Section 7.2 'Installation Using Data Storage'; a parallel USB-memory procedure follows on p.399 with fewer steps — make sure the answer is the SD-card variant.
- sources (any): hmi/mitsubishi/got2000/got2000_gt27_gt25_utility_user_manual.pdf

- [x] OK   - [ ] fix: 

## H06 · procedure

**Q:** How do I enter Calibrate Mode and calibrate the touch panel on an Omron NB-series HMI using the rear DIP switches?

**Expected:** 1. Set rear DIP switches SW1 to OFF and SW2 to ON. 2. Press the Reset switch to restart the NB unit into Calibrate Mode. 3. Touch each '+' shown on the screen (a touch sound confirms each) until the '+' disappears and 'TP Adjust Success!' is displayed. 4. Set both SW1 and SW2 to OFF. 5. Press the Reset switch again. (Alternatively, a Function Key component set to 'Touch Calibration' starts calibration from a project screen.)

- `hmi/omron/nb-series/nb_series_setup_manual.pdf` p.88: "Set the DIP switches SW1 and SW2 on the back side respectively to OFF and ON."
- `hmi/omron/nb-series/nb_series_setup_manual.pdf` p.88: "Set both of the DIP switches SW1 and SW2 to OFF, press the Reset switch again."
- difficulty: long-doc
- ⚠ DIP table on p.35: ON/ON = System Setting Mode, OFF/ON = Calibrate Mode, ON/OFF = Downloader Mode — easy to mix up the switch states.
- sources (any): hmi/omron/nb-series/nb_series_setup_manual.pdf

- [x] OK   - [ ] fix: 

## H07 · procedure

**Q:** How is a Pro-face SP5000 box module (e.g. SP-5B40) attached to the display module or DC power supply adapter?

**Expected:** 1) Pull the LOCK on the top of the Box Module forward to release the lock. 2) Insert the protruding points on the bottom left and right of the Box Module into the two holes on the back of the Display Module (or DC Power Supply Adapter for Box Module) to attach it. 3) Fully push the LOCK on the top of the Box Module to secure it to the Display Module or adapter.

- `hmi/proface/sp5000/sp5000_box_module_installation_guide.pdf` p.21: "Pull the LOCK forward on the top of the Box Module to release the lock as illustrated."
- `hmi/proface/sp5000/sp5000_box_module_installation_guide.pdf` p.22: "Insert the protruding points on the bottom left and right of the Box Module into the two holes on the back of the Display Module"
- difficulty: easy
- ⚠ Only three steps, spread over PDF pages 21-23 (printed page numbers 22-24). The same procedure text also appears in sp5000_series_hardware_manual.pdf, so an answer citing that manual is still correct; the Removal Procedure on p24 is the reverse and must not be confused.
- sources (any): hmi/proface/sp5000/sp5000_box_module_installation_guide.pdf

- [x] OK   - [ ] fix: 

## H08 · procedure

**Q:** What is the installation process for mounting a Beijer X2 pro 4 B2 HMI panel in a cabinet door?

**Expected:** 1) Unpack and check the delivery; notify the supplier of any damage. 2) Cut the opening using the cut-out dimensions in the outline drawing (130 x 89 mm). 3) Make sure the mounting surface of the cutout is smooth and free of burrs/debris. 4) Install the HMI panel into the cutout. 5) Secure it using all fastening holes and the provided brackets and screws, tightened to 0.5 - 1.0 Nm. 6) Where the front seal (IP54+/NEMA-4X) is critical, use a torque wrench to confirm the screw torque. 7) Connect the cables in the specified order (A, then B power using 14-20 AWG at 180-220 N-cm, then C Ethernet, then D). 8) Carefully remove the protective film from the display, avoiding static.

- `hmi/beijer/x2-pro/x2_pro_4_b2_hardware_manual.pdf` p.11: "Unpack and check the delivery. If damage is found, notify the supplier."
- `hmi/beijer/x2-pro/x2_pro_4_b2_hardware_manual.pdf` p.12: "Tighten the screws to 0.5 - 1.0 Nm."
- difficulty: distractor
- ⚠ The X2 pro 10 B2 manual contains the identical 8-step process with the same wording (the X2 pro 15 B2 manual differs slightly in the torque line), so the retriever may cite a sibling manual; the cut-out size (130 x 89 mm, from p14) is specific to the X2 pro 4.
- sources (any): hmi/beijer/x2-pro/x2_pro_4_b2_hardware_manual.pdf

- [x] OK   - [ ] fix: 
