# HMI golden set: review sheet

Tick each item after checking the quote in the PDF.

## A01 · spec

**Q:** What is the maximum power consumption of the PanelView 800 7-inch terminal, catalog number 2711R-T7T?

**Expected:** The 2711R-T7T draws a maximum of 11 W (0.40 A @ 24V DC).

- `hmi/allen-bradley/panelview-800/panelview_800_technical_data.pdf` p.5: "Power Consumption (max) 9 W (0.39 A @ 24V DC) 11 W (0.40 A @ 24V DC) 14 W (0.48 A @ 24V DC)"
- ⚠ Value picked by column position in a flattened power table (9/11/14 W); confirm 11 W is the T7T column.
- sources (any): hmi/allen-bradley/panelview-800/panelview_800_technical_data.pdf

- [ ] OK   - [ ] fix: 

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

**Expected:** It is covered by ATEX certificate DEMKO 19 ATEX 2252 X (marking II 3 G, Ex ec IIC T4 Gc), issued by UL International Demko A/S.

- `hmi/allen-bradley/versaview-5000/versaview_5000_declaration_of_conformity.pdf` p.1: "Type Examination Certificate No. Demko 19 ATEX 2252 X issued by UL"
- `hmi/allen-bradley/versaview-5000/industrial_computers_and_monitors_technical_data.pdf` p.8: "Europe (ATEX) II 3 G, Ex ec IIC T4 Gc, DEMKO 19 ATEX 2252 X"
- `hmi/allen-bradley/versaview-5000/versaview_5000_installation_instructions.pdf` p.3: "Europe (ATEX) II 3 G, Ex ec IIC T4 Gc, DEMKO 19 ATEX 2252 X"
- `hmi/allen-bradley/versaview-5000/versaview_5000_thin_clients_and_industrial_computers_user_manual.pdf` p.19: "Europe (ATEX) II 3 G, Ex ec IIC T4 Gc, DEMKO 19 ATEX 2252 X"
- sources (any): hmi/allen-bradley/versaview-5000/versaview_5000_declaration_of_conformity.pdf, hmi/allen-bradley/versaview-5000/industrial_computers_and_monitors_technical_data.pdf, hmi/allen-bradley/versaview-5000/versaview_5000_installation_instructions.pdf, hmi/allen-bradley/versaview-5000/versaview_5000_thin_clients_and_industrial_computers_user_manual.pdf

- [ ] OK   - [x] fix: 

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

- [ ] OK   - [ ] fix: 

## A12 · comparison

**Q:** How many Ethernet ports does the PanelView 5310 have compared with the PanelView 5510, and which supports Device Level Ring (DLR)?

**Expected:** The PanelView 5310 has one 10/100Base-T Ethernet port, while the PanelView 5510 has two 10/100Base-T Ethernet ports that support DLR (as well as linear and star) topologies.

- `hmi/allen-bradley/panelview-5310/panelview_5310_technical_data.pdf` p.4: "One 10/100Base-T, Auto MDI/MDI-X Ethernet port for controller communication."
- `hmi/allen-bradley/panelview-5310/panelview_5310_user_manual.pdf` p.12: "One 10/100Base-T, Auto MDI/MDI-X, EtherNet/IP port for controller communication."
- `hmi/allen-bradley/panelview-5510/panelview_5510_technical_data.pdf` p.4: "Two 10/100Base-T, Auto MDI/MDIX Ethernet ports that support (Device Level Ring) DLR, linear, or star network topologies."
- `hmi/allen-bradley/panelview-5510/panelview_5510_user_manual.pdf` p.10: "Two 10/100Base-T, Auto MDI/MDIX, EtherNet/IP ports for controller communication that supports DLR network topology."
- sources (all): hmi/allen-bradley/panelview-5310/panelview_5310_technical_data.pdf, hmi/allen-bradley/panelview-5310/panelview_5310_user_manual.pdf, hmi/allen-bradley/panelview-5510/panelview_5510_technical_data.pdf, hmi/allen-bradley/panelview-5510/panelview_5510_user_manual.pdf

- [ ] OK   - [ ] fix: 

## B01 · spec

**Q:** What is the power consumption of the SIMATIC KTP1200 Basic DP (Basic Panels 2nd Generation)?

**Expected:** The KTP1200 Basic DP has a power consumption of 13.2 W (the KTP1200 Basic PN variant is 12.2 W).

- `hmi/siemens/ktp-basic/ktp_basic_panels_2nd_gen_hardware.pdf` p.119: "Power consumption 1 
5.5 W 
12.2 W 
13.2 W"
- ⚠ Value mapped to the model by column order in a flattened table; confirm against the PDF.
- sources (any): hmi/siemens/ktp-basic/ktp_basic_panels_2nd_gen_hardware.pdf

- [ ] OK   - [ ] fix: 

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

- [ ] OK   - [ ] fix: 

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

- [ ] OK   - [ ] fix: 

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

- [ ] OK   - [ ] fix: 

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

- [ ] OK   - [ ] fix: 

## B06 · spec

**Q:** How many tags can the WinCC Unified Runtime tag simulator simulate at the same time?

**Expected:** A maximum of 300 tags can be simulated at the same time, although more tags can be configured and saved in the simulator.

- `hmi/siemens/wincc-unified/wincc_unified_runtime_system_manual.pdf` p.291: "A maximum of 300 tags can be simulated at the same time.
However, you can configure and save more tags in the simulator."
- `hmi/siemens/wincc-unified/wincc_unified_runtime_system_manual.pdf` p.294: "A maximum of 300 tags can be simulated at the same 
time."
- `hmi/siemens/wincc-unified/wincc_unified_runtime_system_manual.pdf` p.297: "You can simulate a maximum of 300 tags simultaneously, even if more tags are configured"
- sources (any): hmi/siemens/wincc-unified/wincc_unified_runtime_system_manual.pdf

- [ ] OK   - [ ] fix: 

## B07 · spec

**Q:** What ambient temperature range is permitted during operation for a Beckhoff CP3716 panel PC (CP37xx series)?

**Expected:** Operation: 0 °C to +45 °C (transport/storage: -20 °C ... +65 °C).

- `hmi/beckhoff/cp3xxx-series/cp37xx_panel_pc_manual.pdf` p.47: "Permissible ambient temperature
Operation: 0 °C to +45 °C
Transport / storage: -20 °C ... +65 °C"
- sources (any): hmi/beckhoff/cp3xxx-series/cp37xx_panel_pc_manual.pdf

- [ ] OK   - [ ] fix: 

## B08 · spec

**Q:** Does the Beckhoff CP6700-0001-0050 panel PC have fTPM 2.0 enabled?

**Expected:** No. The CP6700-0001-0050 has fTPM 2.0 not enabled; the CP6700-0001-0060 and CP6700-0001-0070 have fTPM 2.0 enabled.

- `hmi/beckhoff/cp6000-series/cp6700_panel_pc.pdf` p.40: "CP6700-0001-0050: fTPM 2.0 not enabled
CP6700-0001-0060: fTPM 2.0 enabled
CP6700-0001-0070: fTPM 2.0 enabled"
- sources (any): hmi/beckhoff/cp6000-series/cp6700_panel_pc.pdf

- [ ] OK   - [ ] fix: 

## B09 · spec

**Q:** What are the dimensions (W x H x D) of the Advantech WebOP-2080V (WOP-2080V-N4AE) operator panel?

**Expected:** 232.5 x 175.8 x 42.9 mm (9.15" x 6.92" x 1.69").

- `hmi/advantech/webop-3000t/advantech_industrial_operator_panels_catalog.pdf` p.1: "232.5 x 175.8 x 42.9mm 
(9.15" x 6.92" x 1.69")"
- sources (any): hmi/advantech/webop-3000t/advantech_industrial_operator_panels_catalog.pdf

- [ ] OK   - [ ] fix: 

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

- [ ] OK   - [ ] fix: 

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

- [ ] OK   - [ ] fix: 

## C01 · spec

**Q:** When connecting a Mitsubishi GOT2000 to a KEYENCE PLC over Ethernet, what is the default port No. of the connected Ethernet module in the Connected Ethernet Controller Setting?

**Expected:** The default port No. of the connected KEYENCE Ethernet module is 8501 (set to match the PLC side port No.).

- `hmi/mitsubishi/got2000/got2000_connection_manual_non_mitsubishi_products_1.pdf` p.338: "Port No. Set the port No. of the connected Ethernet module. (Default: 8501)"
- sources (any): hmi/mitsubishi/got2000/got2000_connection_manual_non_mitsubishi_products_1.pdf

- [ ] OK   - [ ] fix: 

## C02 · spec

**Q:** How many Mitsubishi GOT2000 units can be connected as DeviceNet slaves to one DeviceNet master?

**Expected:** Up to 63 GOT modules (DeviceNet slave equipment) can be connected to one DeviceNet master equipment.

- `hmi/mitsubishi/got2000/got2000_connection_manual_microcomputer_modbus.pdf` p.241: "Up to 63 GOT modules (DeviceNet slave equipment) can be connected to one DeviceNet master equipment."
- sources (any): hmi/mitsubishi/got2000/got2000_connection_manual_microcomputer_modbus.pdf

- [ ] OK   - [ ] fix: 

## C03 · spec

**Q:** What is the maximum power consumption of the Mitsubishi GOT Simple GS2107-WTBD?

**Expected:** The GS2107-WTBD consumes 6.5 W (271 mA/24 V) or less (3.8 W (158 mA/24 V) or less with the backlight off).

- `hmi/mitsubishi/got-simple-gs21/gs25_gs21_user_manual.pdf` p.146: "Power consumption 7.6 W (317 mA/24 V) or less 6.5 W (271 mA/24 V) or less 7.6 W (317 mA/24 V) or less 6.5 W (271 mA/24 V) or less"
- `hmi/mitsubishi/got-simple-gs21/gs21_general_description.pdf` p.1: "GS2110-WTBD GS2107-WTBD Input power supply voltage 24VDC (+10% -15%), ripple voltage 200mV or less Power consumption 7.6W (317mA/24V) or less 6.5W (271mA/24V) or less"
- `hmi/mitsubishi/got-simple-gs21/got_simple_series_catalog.pdf` p.36: "Power consumption 7.6 W (317 mA/24 V) or less 6.5 W (271 mA/24 V) or less"
- sources (any): hmi/mitsubishi/got-simple-gs21/gs25_gs21_user_manual.pdf, hmi/mitsubishi/got-simple-gs21/gs21_general_description.pdf, hmi/mitsubishi/got-simple-gs21/got_simple_series_catalog.pdf

- [ ] OK   - [ ] fix: 

## C04 · spec

**Q:** What is the built-in clock precision of the Mitsubishi GT2107-W (GT21 wide model)?

**Expected:** The GT2107-W built-in clock precision is ±45 seconds/month at an ambient temperature of 25 °C.

- `hmi/mitsubishi/got2000/got2000_gt27_gt25_hardware_user_manual.pdf` p.102: "Built-in clock precision ±45 seconds/month (Ambient temperature: 25 °C)"
- `hmi/mitsubishi/got2000/got2000_series_catalog.pdf` p.21: "Built-in clock precision ±45 seconds/month (ambient temperature: 25 °C)"
- sources (any): hmi/mitsubishi/got2000/got2000_gt27_gt25_hardware_user_manual.pdf, hmi/mitsubishi/got2000/got2000_series_catalog.pdf

- [ ] OK   - [ ] fix: 

## C05 · spec

**Q:** What does the Omron NB10W-TW01B (non-V1) HMI weigh?

**Expected:** The NB10W-TW01B weighs 1525 g (power consumption 14 W).

- `hmi/omron/nb-series/nb_series_setup_manual.pdf` p.90: "NB10W-TW01B 14W 1525g"
- `hmi/omron/nb-series/nb_series_startup_guide.pdf` p.29: "NB10W-TW01B 14W 1525g"
- sources (any): hmi/omron/nb-series/nb_series_setup_manual.pdf, hmi/omron/nb-series/nb_series_startup_guide.pdf

- [ ] OK   - [ ] fix: 

## C06 · spec

**Q:** Which communication protocol does an Omron NA-series HMI use to connect to an OMRON Programmable Multi-Axis Controller (Power PMAC), and what must be entered on the controller side to enable it?

**Expected:** The NA connects via Modbus/TCP (Communication Driver "Modbus/TCP", Device Series "CK3"), and the command Sys.ModbusServerEnable=1 must be entered from the PowerPMAC IDE terminal.

- `hmi/omron/na-series/na_series_device_connection_user_manual.pdf` p.108: "You can connect a NA-series Programmable Terminal to a Programmable Multi-Axis Controller using Modbus/TCP."
- `hmi/omron/na-series/na_series_device_connection_user_manual.pdf` p.109: "The following command must be entered from the PowerPMAC IDE terminal. Sys.ModbusServerEnable=1"
- `hmi/omron/na-series/na_series_device_connection_user_manual.pdf` p.111: "Communication Driver: Select "Modbus/TCP"."
- sources (any): hmi/omron/na-series/na_series_device_connection_user_manual.pdf

- [ ] OK   - [ ] fix: 

## C07 · spec

**Q:** What is the ambient operating temperature range of the Omron NSH5 hand-held PT (NSH5-V2)?

**Expected:** The NSH5-V2 hand-held PT is rated for an ambient operating temperature of 0 to 40°C (power consumption 10 W max.).

- `hmi/omron/ns-series/ns_series_datasheet.pdf` p.39: "Power consumption 10 W max. Ambient operating temperature 0 to 40C"
- sources (any): hmi/omron/ns-series/ns_series_datasheet.pdf

- [ ] OK   - [ ] fix: 

## C08 · spec

**Q:** In Delta DOPSoft, how many actions can be configured on a single Multiple actions button?

**Expected:** Up to 32 actions can be set for each of press, release and long press, so one Multiple actions button can execute up to 32*3 (96) actions.

- `hmi/delta/dop-100/dopsoft_user_manual.pdf` p.376: "You can set up to 32 actions for each press, release, and long press, so one Multiple actions button can execute up to 32*3 actions."
- sources (any): hmi/delta/dop-100/dopsoft_user_manual.pdf

- [ ] OK   - [ ] fix: 

## C09 · spec

**Q:** What is the display resolution of the Delta DOP-110WS 10.1" HMI?

**Expected:** The DOP-110WS has a resolution of 1024 x 600 pixels.

- `hmi/delta/dop-100/dop_100_series_catalog.pdf` p.26: "Resolution (Pixels) 480 x 272 800 x 480 1024 x 600"
- `hmi/delta/dop-100/dop_100_series_selection_guide.pdf` p.28: "Resolution (Pixels) 480 x 272 800 x 480 1,024 x 600"
- sources (any): hmi/delta/dop-100/dop_100_series_catalog.pdf, hmi/delta/dop-100/dop_100_series_selection_guide.pdf

- [ ] OK   - [ ] fix: 

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

- [ ] OK   - [ ] fix: 

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

- [ ] OK   - [ ] fix: 

## D01 · spec

**Q:** What input voltage range does the Weintek MT8071iP accept?

**Expected:** The MT8071iP accepts a wide input voltage range of 10.5~28VDC (power consumption 1A@12VDC; 500mA@24VDC).

- `hmi/weintek/ip-series/mt8071ip1_datasheet.pdf` p.1: "Input Power 
10.5~28VDC 
Power Consumption 
1A@12VDC ; 500mA@24VDC"
- `hmi/weintek/ip-series/mt8071ip1_datasheet.pdf` p.1: "Wide input voltage range: 10.5~28VDC"
- sources (any): hmi/weintek/ip-series/mt8071ip1_datasheet.pdf

- [ ] OK   - [ ] fix: 

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

- [ ] OK   - [ ] fix: 

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

- [ ] OK   - [ ] fix: 

## D04 · spec

**Q:** What is the input power requirement of the Red Lion Graphite G310C, including maximum wattage?

**Expected:** The G310C requires +24 VDC ±20% at 33 W maximum (a 24 VDC supply rated at 33 W).

- `hmi/red-lion/graphite/g310c_datasheet.pdf` p.2: "G310C: +24 VDC ±20% @ 33 W maximum."
- `hmi/red-lion/graphite/g310c_datasheet.pdf` p.3: "The G310C requires a 24 VDC power supply rated at 33 W"
- sources (any): hmi/red-lion/graphite/g310c_datasheet.pdf

- [ ] OK   - [ ] fix: 

## D05 · spec

**Q:** How much does the Red Lion Graphite G315C weigh?

**Expected:** The G315C weighs 11.41 lbs (5.17 Kg).

- `hmi/red-lion/graphite/g315c_datasheet.pdf` p.2: "13. WEIGHT: 11.41 lbs (5.17 Kg)"
- sources (any): hmi/red-lion/graphite/g315c_datasheet.pdf

- [ ] OK   - [ ] fix: 

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

- [ ] OK   - [ ] fix: 

## D07 · spec

**Q:** What panel cutout is required to mount a Pro-face STM-6400WA display module?

**Expected:** The STM-6200WA/STM-6400WA display modules mount in a round hole of diameter 22.5 mm (0.88 in), toleranced 22.5 mm (+0/-0.3 mm).

- `hmi/proface/stm6000/stm6000_series_hardware_manual.pdf` p.22: "Panel cut dimensions
Diameter 22.5 mm (0.88 in)"
- `hmi/proface/stm6000/stm6000_series_hardware_manual.pdf` p.38: "22.5 mm (+0/-0.3 mm)
(0.88 in [+0/-0.01 in])"
- sources (any): hmi/proface/stm6000/stm6000_series_hardware_manual.pdf

- [ ] OK   - [ ] fix: 

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

- [ ] OK   - [ ] fix: 

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

- [ ] OK   - [ ] fix: 

## D10 · comparison

**Q:** Compare the operating temperature ranges of the Weintek eMT3070A and eMT3150A.

**Expected:** The eMT3070A operates from -20° ~ 50°C (-4° ~ 122°F), while the eMT3150A operates from 0° ~ 50°C (32° ~ 122°F), so the eMT3070A tolerates colder environments.

- `hmi/weintek/emt-series/emt3070a_7in_datasheet.pdf` p.1: "Operating Temperature 
-20° ~ 50°C (-4° ~ 122°F)"
- `hmi/weintek/emt-series/emt3150a_15in_datasheet.pdf` p.1: "Operating Temperature 
0° ~ 50°C (32° ~ 122°F)"
- sources (all): hmi/weintek/emt-series/emt3070a_7in_datasheet.pdf, hmi/weintek/emt-series/emt3150a_15in_datasheet.pdf

- [ ] OK   - [ ] fix: 

## D11 · comparison

**Q:** How do the Red Lion FlexEdge DA50A and DA70A compare in weight?

**Expected:** The DA50A weighs 13 oz (404.3 g), while the DA70A weighs 2 lb 2.5 oz (978.05 g).

- `hmi/red-lion/flexedge/flexedge_da50a_datasheet.pdf` p.3: "Polycarbonate enclosure with IP30 rating.
Weight: 13 oz (404.3 g)"
- `hmi/red-lion/flexedge/flexedge_da70a_datasheet.pdf` p.3: "Metal and plastic enclosure with IP30 rating.
Weight: 2 lb 2.5 oz (978.05 g)"
- sources (all): hmi/red-lion/flexedge/flexedge_da50a_datasheet.pdf, hmi/red-lion/flexedge/flexedge_da70a_datasheet.pdf

- [ ] OK   - [ ] fix: 

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

- [ ] OK   - [ ] fix: 

## E01 · unanswerable

**Q:** What is the MTBF of the Weintek cMT3072X?

**Expected:** The documents do not state an MTBF for the Weintek cMT3072X. The answer should say so and must not borrow an MTBF from another vendor's product.

- absence check: grep -rilE 'MTBF|mean time' hmi/weintek -> 0 files (MTBF appears only in 9 Siemens files)
- sources (none): —

- [ ] OK   - [ ] fix: 

## E02 · unanswerable

**Q:** What is the list price of the Allen-Bradley PanelView 5510?

**Expected:** The documents contain no pricing for the PanelView 5510. The answer should say pricing isn't in the library.

- absence check: grep -ilE 'price|USD|€|\$ ?[0-9]' hmi/allen-bradley/panelview-5510/* -> 0 files
- sources (none): —

- [ ] OK   - [ ] fix: 

## E03 · unanswerable

**Q:** Which Bluetooth version does the Weintek cMT3162X support?

**Expected:** The documents do not mention Bluetooth for the cMT3162X (or any product). The answer should say this isn't stated rather than invent a version.

- absence check: grep -rilE bluetooth hmi/ -> 0 files; cMT3162X exists (cmt3162x_15in_datasheet)
- sources (none): —

- [ ] OK   - [ ] fix: 

## E04 · unanswerable

**Q:** What is the operating temperature range of the Weintek cMT3252X?

**Expected:** There is no cMT3252X in the library, so its operating temperature cannot be answered. The answer should say so and must not substitute a similar model's range.

- absence check: grep -ril cMT3252 hmi/ -> 0 files; similarly named cMT models exist
- sources (none): —

- [ ] OK   - [ ] fix: 

## E05 · unanswerable

**Q:** What is the display resolution of the Phoenix Contact BTP 2070W HMI?

**Expected:** The library has no Phoenix Contact HMI documentation (Phoenix Contact appears only as a connectable PLC in connection manuals), so this cannot be answered from the documents.

- absence check: grep -rilE 'BTP ?2070' hmi/ -> 0 files; 'Phoenix Contact' only in connection manuals
- sources (none): —

- [ ] OK   - [ ] fix: 

## E06 · unanswerable

**Q:** Which Linux kernel version does the Red Lion Graphite G310 run?

**Expected:** The Red Lion documents do not mention Linux or a kernel version for the Graphite G310. The answer should say this isn't stated.

- absence check: grep -rilE '\blinux\b' hmi/red-lion -> 0 files
- sources (none): —

- [ ] OK   - [ ] fix: 

## E07 · library

**Q:** Which HMI vendors are covered in the document library?

**Expected:** 12 vendors: Advantech, Allen-Bradley (Rockwell, incl. ASEM), Beckhoff, Beijer, Delta, Mitsubishi, Omron, Pro-face, Red Lion, Schneider, Siemens and Weintek.

- sources (none): —

- [ ] OK   - [ ] fix: 

## E08 · library

**Q:** How many Weintek documents are in the library?

**Expected:** 18 Weintek documents (datasheets, installation guide and brochures across the cMT, cMT-X, eMT, iE, iP, cMT-SVR and gateway series).

- sources (none): —

- [ ] OK   - [ ] fix: 

## E09 · library

**Q:** Which documents cover the Mitsubishi GOT2000 series?

**Expected:** 10 documents: got2000_connection_manual_microcomputer_modbus.pdf; got2000_connection_manual_non_mitsubishi_products_1.pdf; got2000_connection_manual_non_mitsubishi_products_2.pdf; got2000_graphic_operation_catalog.pdf; got2000_gt27_gt25_hardware_user_manual.pdf; got2000_gt27_gt25_utility_user_manual.pdf; got2000_series_catalog.pdf; gt21_wide_general_description.pdf; gt25_wide_general_description.pdf; gt27_general_description.pdf.

- sources (none): —

- [ ] OK   - [ ] fix: 

## F01 · followup

**Q:** Which replacement battery does it take for the real-time clock?

**Expected:** Use catalog number 2711P-Y2032 (or a manufacturer's equivalent such as the Matsushita or Duracell DL2032 lithium battery).

- `hmi/allen-bradley/panelview-800/panelview_800_user_manual.pdf` p.130: "only replace the battery with 2711P-Y2032 or a manufacturer"
- history: [{'user': 'What is the maximum power consumption of the PanelView 800 2711R-T7T?', 'assistant': 'The 2711R-T7T draws a maximum of 11 W (0.40 A @ 24V DC).'}]
- sources (any): hmi/allen-bradley/panelview-800/panelview_800_user_manual.pdf

- [ ] OK   - [ ] fix: 

## F02 · followup

**Q:** What IP rating does its stainless-steel version have?

**Expected:** The PanelView 5510 stainless-steel terminal (2715P-T12WD-BSK) is rated IP69 as classified by UL and tested for IP69K according to ISO 20653.

- `hmi/allen-bradley/panelview-5510/panelview_5510_technical_data.pdf` p.3: "Rated IP69 as Classified by UL. Tested for IP69K according to ISO 20653."
- history: [{'user': 'How many Ethernet ports does the PanelView 5510 have?', 'assistant': 'Two 10/100Base-T Ethernet ports that support Device Level Ring (DLR).'}]
- ⚠ Stainless model ↔ IP69 mapping comes from a flattened table on p.3; confirm against the PDF.
- sources (any): hmi/allen-bradley/panelview-5510/panelview_5510_technical_data.pdf

- [ ] OK   - [ ] fix: 

## F03 · followup

**Q:** How does that compare with Delta's 7-inch DOP-107WV?

**Expected:** The Delta DOP-107WV draws Max. 8.4 W, so it uses less than half the NA5-7W's 19 W max.

- `hmi/delta/dop-100/dop_100_series_catalog.pdf` p.26: "Power Consumption *5 Max. 5.8 W *3 Max. 8.4 W *3 Max. 11 W"
- `hmi/delta/dop-100/dop_100_series_selection_guide.pdf` p.28: "Power Consumption *5 Max. 5.8 W *3 Max. 8.4 W *3 Max. 11 W"
- history: [{'user': 'What is the maximum power consumption of the Omron NA5-7W?', 'assistant': '19 W max.'}]
- ⚠ DOP-107WV 8.4 W is the middle column of a flattened table; confirm against the PDF.
- sources (any): hmi/delta/dop-100/dop_100_series_catalog.pdf, hmi/delta/dop-100/dop_100_series_selection_guide.pdf

- [ ] OK   - [ ] fix: 

## F04 · followup

**Q:** And the DA70A?

**Expected:** The FlexEdge DA70A weighs 2 lb 2.5 oz (978.05 g).

- `hmi/red-lion/flexedge/flexedge_da70a_datasheet.pdf` p.3: "Metal and plastic enclosure with IP30 rating.
Weight: 2 lb 2.5 oz (978.05 g)"
- history: [{'user': 'How much does the Red Lion FlexEdge DA50A weigh?', 'assistant': '13 oz (404.3 g).'}]
- sources (any): hmi/red-lion/flexedge/flexedge_da70a_datasheet.pdf

- [ ] OK   - [ ] fix: 

## F05 · followup

**Q:** What about the cMT3072X?

**Expected:** The Weintek cMT3072X has an 800 x 480 display (7" TFT).

- `hmi/weintek/cmt-x-series/cmt3072x_datasheet.pdf` p.1: "Display 
7” TFT 
Resolution 
800 x 480 
Brightness (cd/m2) 
400"
- history: [{'user': 'What is the display resolution of the Weintek cMT3072XH?', 'assistant': '1024 x 600 (7" IPS).'}]
- DISTRACTOR (must NOT be cited) `hmi/weintek/cmt-x-series/cmt3072xh_datasheet.pdf` p.1: "Display 
7” IPS 
Resolution 
1024 x 600 
Brightness (cd/m2) 
450"
- ⚠ Must cite the cMT3072X sheet, not the cMT3072XH one from the previous turn.
- sources (any): hmi/weintek/cmt-x-series/cmt3072x_datasheet.pdf

- [ ] OK   - [ ] fix: 

