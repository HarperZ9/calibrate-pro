"""
Built-in panel characterization data.

Contains factory-measured panel characteristics for 58 monitors,
used for sensorless calibration when no external profile is available.
"""


from calibrate_pro.panels.panel_types import (
    ChromaticityCoord,
    DDCRecommendations,
    GammaCurve,
    PanelCapabilities,
    PanelCharacterization,
    PanelPrimaries,
)


def get_builtin_panels() -> dict[str, PanelCharacterization]:
    """Return all built-in panel characterizations.

    Returns:
        Dict mapping panel key to PanelCharacterization.
    """
    panels: dict[str, PanelCharacterization] = {}

    # ASUS ROG Swift OLED PG27UCDM (Samsung QD-OLED panel - 2024 generation)
    panels["PG27UCDM"] = PanelCharacterization(
        manufacturer="ASUS",
        model_pattern=r"PG27UCDM|ROG.*PG27UCDM|PG27.*UCDM",
        panel_type="QD-OLED",
        display_name="ROG Swift OLED PG27UCDM",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6795, 0.3095),
            green=ChromaticityCoord(0.2325, 0.7115),
            blue=ChromaticityCoord(0.1375, 0.0495),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2020, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1980, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=275.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom 1",
            picture_mode_vcp=0x0B,
            color_preset="User",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=40,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom 1 picture mode for unlocked RGB gain controls. "
                  "Disable ELMB Sync for stable DDC communication. "
                  "VRR (Adaptive-Sync) can remain on. Uniform Brightness recommended off. "
                  "OSD gamma options: 1.8, 2.0, 2.2, 2.4, 2.6."
        ),
        notes="ASUS ROG Swift 27-inch 4K 240Hz QD-OLED. Samsung Display 2024 panel. 92% BT.2020."
    )

    # Samsung Odyssey OLED G85SB (Samsung QD-OLED panel)
    panels["G85SB"] = PanelCharacterization(
        manufacturer="Samsung",
        model_pattern=r"G85SB|Odyssey.*G85SB|LS34BG850S",
        panel_type="QD-OLED",
        display_name="Odyssey OLED G8 G85SB",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6780, 0.3080),
            green=ChromaticityCoord(0.2340, 0.7100),
            blue=ChromaticityCoord(0.1380, 0.0510),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2050, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1980, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2020, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=250.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.0001,
            native_contrast=1000000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom",
            picture_mode_vcp=0x0B,
            color_preset="Custom",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=45,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom picture mode for DDC/CI RGB gain access. "
                  "Disable game features (Game Mode, VRR) during calibration for stable DDC. "
                  "Dynamic Brightness must be off. Core Lighting sync may interfere - disable. "
                  "Color temperature presets: Custom, Warm, Normal, Cool."
        ),
        notes="Samsung QD-OLED with wider gamut than WOLED. May need slight chroma adjustment."
    )

    # Dell Alienware AW3423DW (Samsung QD-OLED)
    panels["AW3423DW"] = PanelCharacterization(
        manufacturer="Dell",
        model_pattern=r"AW3423DW|Alienware.*3423",
        panel_type="QD-OLED",
        display_name="Alienware AW3423DW",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6780, 0.3080),
            green=ChromaticityCoord(0.2340, 0.7100),
            blue=ChromaticityCoord(0.1380, 0.0510),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2100, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1950, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2050, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=200.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.0001,
            native_contrast=1000000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom Color",
            picture_mode_vcp=0x0B,
            color_preset="Custom Color",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=45,
            initial_contrast=75,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom Color mode for full DDC/CI control over RGB gains. "
                  "Disable Smart HDR (Creator mode) as it interferes with DDC adjustments. "
                  "Gamma options in OSD: 2.2, 2.4, sRGB, BT.1886, PQ. "
                  "Set color space to Wide for full gamut, or sRGB to clamp."
        ),
        notes="First consumer QD-OLED. Same panel as G85SB with Dell calibration."
    )

    # Dell Alienware AW3423DWF (Samsung QD-OLED - FreeSync Edition)
    # Source: Rtings.com measurements
    panels["AW3423DWF"] = PanelCharacterization(
        manufacturer="Dell",
        model_pattern=r"AW3423DWF|Alienware.*3423DWF",
        panel_type="QD-OLED",
        display_name="Alienware AW3423DWF",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6780, 0.3080),
            green=ChromaticityCoord(0.2340, 0.7100),
            blue=ChromaticityCoord(0.1380, 0.0510),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2080, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1960, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2040, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=210.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.0001,
            native_contrast=1000000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom Color",
            picture_mode_vcp=0x0B,
            color_preset="Custom Color",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=45,
            initial_contrast=75,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom Color mode for full DDC/CI control over RGB gains. "
                  "Disable Creator mode Smart HDR as it overrides DDC brightness/contrast. "
                  "Gamma options: 2.2, 2.4, sRGB, BT.1886, PQ. "
                  "FreeSync edition - no G-Sync module, DDC/CI more reliable over DP."
        ),
        notes="FreeSync QD-OLED. Same Samsung panel as AW3423DW. Source: Rtings."
    )

    # Dell Alienware AW3225QF (Samsung QD-OLED 4K 32" - 2024)
    # Source: Rtings.com measurements, TFTCentral review
    panels["AW3225QF"] = PanelCharacterization(
        manufacturer="Dell",
        model_pattern=r"AW3225QF|Alienware.*3225|AW3225",
        panel_type="QD-OLED",
        display_name="Alienware AW3225QF",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6792, 0.3098),
            green=ChromaticityCoord(0.2318, 0.7108),
            blue=ChromaticityCoord(0.1372, 0.0498),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2015, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1985, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=275.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom Color",
            picture_mode_vcp=0x0B,
            color_preset="Custom Color",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=45,
            initial_contrast=75,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom Color mode for full DDC/CI RGB gain access. "
                  "Enable DDC/CI in Others menu. Creator mode with sRGB or DCI-P3 gamut "
                  "is accurate but locks color controls. Smart HDR modes: Desktop, Movie HDR, "
                  "Game HDR, Custom Color HDR, DisplayHDR 400 True Black, HDR Peak 1000. "
                  "Preset modes: Standard, Creator (DCI-P3/sRGB selectable), FPS, MOBA/RTS, RPG, Sports. "
                  "Dark Stabilizer manipulates gamma - disable for calibration. "
                  "Color temp presets: Warm, Cool, Custom. Dell Display Manager works over DP and HDMI."
        ),
        notes="Samsung 2024 QD-OLED 4K panel. 99.3% DCI-P3, Delta E 1.8 out of box. Source: Rtings/TFTCentral."
    )

    # ASUS ROG Swift PG32UCDM (Samsung QD-OLED 4K 32")
    # Source: Hardware Unboxed review measurements
    panels["PG32UCDM"] = PanelCharacterization(
        manufacturer="ASUS",
        model_pattern=r"PG32UCDM|ROG.*PG32UCDM|PG32.*UCDM",
        panel_type="QD-OLED",
        display_name="ROG Swift OLED PG32UCDM",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6798, 0.3102),
            green=ChromaticityCoord(0.2322, 0.7112),
            blue=ChromaticityCoord(0.1378, 0.0502),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2025, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1990, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2010, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=280.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom 1",
            picture_mode_vcp=0x0B,
            color_preset="User",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=40,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom 1 picture mode for unlocked RGB gain controls. "
                  "DDC/CI enable in OSD Setup menu. Disable ELMB Sync for stable DDC comm. "
                  "Picture modes: Scenery, Racing, Cinema, RTS/RPG, FPS, Night Vision, User. "
                  "Blue Light Filter affects white point - disable for calibration. "
                  "OSD gamma options: 1.8, 2.0, 2.2, 2.4, 2.6. "
                  "VRR (Adaptive-Sync) can remain on. Uniform Brightness recommended off."
        ),
        notes="32-inch sibling of PG27UCDM. Same Samsung QD-OLED panel. Source: Hardware Unboxed."
    )

    # Samsung Odyssey OLED G8 G80SD (QD-OLED 32" 4K)
    # Source: Rtings.com measurements
    panels["G80SD"] = PanelCharacterization(
        manufacturer="Samsung",
        model_pattern=r"G80SD|Odyssey.*G80SD|LS32DG802S|G8.*OLED",
        panel_type="QD-OLED",
        display_name="Odyssey OLED G8 G80SD",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6785, 0.3095),
            green=ChromaticityCoord(0.2330, 0.7105),
            blue=ChromaticityCoord(0.1375, 0.0505),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2010, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1995, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2005, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=270.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom",
            picture_mode_vcp=0x0B,
            color_preset="Custom",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=45,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom picture mode for DDC/CI RGB gain access. "
                  "Disable Game Mode and Adaptive-Sync during calibration for stable DDC. "
                  "Dynamic Brightness must be off. Core Lighting sync may interfere. "
                  "Color temp presets: Custom, Warm, Normal, Cool."
        ),
        notes="Samsung's own 32-inch 4K QD-OLED. Very accurate out of box. Source: Rtings."
    )

    # Samsung Odyssey G95SC (QD-OLED 49" Super Ultrawide)
    # Source: TFTCentral, Hardware Unboxed
    panels["G95SC"] = PanelCharacterization(
        manufacturer="Samsung",
        model_pattern=r"G95SC|Odyssey.*G95SC|LS49CG950S|G9.*OLED",
        panel_type="QD-OLED",
        display_name="Odyssey OLED G9 G95SC",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6782, 0.3085),
            green=ChromaticityCoord(0.2338, 0.7098),
            blue=ChromaticityCoord(0.1382, 0.0512),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2080, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1960, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2020, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=250.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.0001,
            native_contrast=1000000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom",
            picture_mode_vcp=None,
            color_preset="Custom",
            color_preset_vcp=None,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=40,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=None,
            notes="WARNING: Samsung Odyssey OLED G9 G95SC has severely limited DDC/CI support. "
                  "DDC/CI does not work over DisplayPort on most Samsung monitors - HDMI only. "
                  "Many standard VCP codes are not implemented. Input switching via DDC is unsupported. "
                  "Use Custom picture mode in OSD manually. Preset modes: Eco (default), Movie, Custom. "
                  "Movie mode has best default grayscale/gamma (BT.1886). "
                  "Color space: Auto (sRGB clamp) or Native (wide). "
                  "Dynamic Brightness must be off. Eye Saver Mode must be off. "
                  "Calibration primarily requires manual OSD adjustment rather than DDC/CI automation."
        ),
        notes="49-inch 5120x1440 QD-OLED ultrawide. 32:9 aspect. Source: TFTCentral/Hardware Unboxed."
    )

    # LG C3 OLED (WOLED TV used as monitor - 42/48/55 inch)
    # Source: Rtings.com TV calibration data, HDTVTest
    panels["LG_C3"] = PanelCharacterization(
        manufacturer="LG",
        model_pattern=r"OLED42C3|OLED48C3|OLED55C3|LG.*C3|OLED.*C3",
        panel_type="WOLED",
        display_name="C3 OLED",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6399, 0.3301),
            green=ChromaticityCoord(0.2998, 0.5998),
            blue=ChromaticityCoord(0.1502, 0.0601),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=180.0,
            max_luminance_hdr=800.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Game Optimizer",
            picture_mode_vcp=0x0B,
            color_preset="Warm 50",
            color_preset_vcp=0x05,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=85,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="BT.1886",
            gamma_vcp_value=0x08,
            notes="Use Game Optimizer or Filmmaker mode for DDC/CI access. "
                  "Disable AI Brightness (AI Picture Pro) as it overrides DDC brightness. "
                  "Disable ASBL (Auto Static Brightness Limiter) via service menu if possible. "
                  "Enable HDMI ULTRA HD Deep Color for 10-bit. Set HDMI input label to PC. "
                  "Color temp presets: Warm 50, Warm 30, Medium, Cool. Use Warm 50 for D65."
        ),
        notes="LG WOLED evo panel. Excellent for gaming. Use PC mode. Source: Rtings/HDTVTest."
    )

    # LG C4 OLED (2024 WOLED evo)
    # Source: Rtings.com, Vincent Teoh HDTVTest
    panels["LG_C4"] = PanelCharacterization(
        manufacturer="LG",
        model_pattern=r"OLED42C4|OLED48C4|OLED55C4|OLED65C4|LG.*C4|OLED.*C4",
        panel_type="WOLED",
        display_name="C4 OLED",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6398, 0.3302),
            green=ChromaticityCoord(0.2999, 0.5997),
            blue=ChromaticityCoord(0.1501, 0.0602),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2005, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1998, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2002, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=200.0,
            max_luminance_hdr=850.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Filmmaker",
            picture_mode_vcp=0x0B,
            color_preset="Warm 50",
            color_preset_vcp=0x05,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=85,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="BT.1886",
            gamma_vcp_value=0x08,
            notes="Use Filmmaker or Game Optimizer mode for DDC/CI access. "
                  "Disable AI Brightness (AI Picture Pro) as it overrides DDC brightness. "
                  "Disable ASBL via service menu if possible for stable luminance. "
                  "Enable HDMI ULTRA HD Deep Color for 10-bit. Set HDMI label to PC. "
                  "Color temp presets: Warm 50, Warm 30, Medium, Cool. Use Warm 50 for D65."
        ),
        notes="2024 LG WOLED evo with improved brightness. Excellent factory calibration. Source: Rtings/HDTVTest."
    )

    # LG 27GP950-B (Nano IPS)
    # Source: TFTCentral measurements, Rtings
    panels["27GP950"] = PanelCharacterization(
        manufacturer="LG",
        model_pattern=r"27GP950|UltraGear.*27GP950",
        panel_type="Nano-IPS",
        display_name="UltraGear 27GP950-B",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3320),
            green=ChromaticityCoord(0.2750, 0.6400),
            blue=ChromaticityCoord(0.1495, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2150, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2100, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2120, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=400.0,
            max_luminance_hdr=600.0,
            min_luminance=0.08,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Gamer 1",
            picture_mode_vcp=0x0B,
            color_preset="Custom",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=70,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="Mode 3",
            gamma_vcp_value=0x04,
            notes="Use Gamer 1 or Gamer 2 picture mode for DDC/CI RGB gain access. "
                  "sRGB mode clamps gamut and locks brightness/contrast/color controls. "
                  "Picture modes: FPS, RTS, sRGB, Reader, Gamer 1, Gamer 2, Calibration 1, Calibration 2. "
                  "Gamma modes: Mode 1 (2.0), Mode 2 (2.2), Mode 3 (2.4), Mode 4 (2.6). "
                  "Color temp: Custom, 6500K, 7500K, 9300K. 6-axis hue/saturation available. "
                  "LG Calibration Studio supports hardware calibration into Calibration 1/2 slots. "
                  "HDMI ULTRA HD Deep Color must be enabled for 10-bit. "
                  "On-Screen Control app provides DDC/CI access from desktop."
        ),
        notes="Nano IPS with 98% DCI-P3. Good for HDR600 content. Source: TFTCentral/Rtings."
    )

    # BenQ PD3220U (IPS - Professional color work)
    # Source: TFTCentral professional review
    panels["PD3220U"] = PanelCharacterization(
        manufacturer="BenQ",
        model_pattern=r"PD3220U|BenQ.*PD3220",
        panel_type="IPS",
        display_name="DesignVue PD3220U",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6495, 0.3380),
            green=ChromaticityCoord(0.2680, 0.6550),
            blue=ChromaticityCoord(0.1490, 0.0550),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=300.0,
            max_luminance_hdr=300.0,
            min_luminance=0.25,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=False,
            wide_gamut=True,
            vrr_capable=False,
            local_dimming=False
        ),
        notes="Professional 4K monitor. Factory calibrated Delta E < 2. Thunderbolt 3. Source: TFTCentral."
    )

    # ASUS ProArt PA32UCG-K (Mini-LED)
    # Source: TFTCentral, Rtings professional review
    panels["PA32UCG"] = PanelCharacterization(
        manufacturer="ASUS",
        model_pattern=r"PA32UCG|ProArt.*PA32UCG",
        panel_type="Mini-LED",
        display_name="ProArt PA32UCG",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6780, 0.3100),
            green=ChromaticityCoord(0.2650, 0.6900),
            blue=ChromaticityCoord(0.1380, 0.0520),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=600.0,
            max_luminance_hdr=1600.0,
            min_luminance=0.005,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=False,
            local_dimming=True,
            local_dimming_zones=1152
        ),
        ddc=DDCRecommendations(
            picture_mode="User Mode 1",
            picture_mode_vcp=0x0B,
            color_preset="User",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use User Mode 1 or User Mode 2 for full DDC/CI RGB gain access. "
                  "Picture modes: Standard, sRGB, Adobe RGB, DCI-P3, Rec.2020, DICOM, "
                  "Rec.709, HDR_PQ DCI, HDR_PQ Rec.2020, HDR_HLG, HDR_HLG DCI, "
                  "Dolby Vision, User Mode 1, User Mode 2. "
                  "Color temp: 9300K, 6500K, 5500K, 5000K, P3-Theater (DCI-P3 only). "
                  "Gamma options: 1.8, 2.0, 2.2, 2.4, 2.6. "
                  "6-axis color adjustment (R/G/B/C/M/Y) available. "
                  "ProArt Calibration software stores profiles to User Mode 1/2. "
                  "1152 Mini-LED zones - local dimming may affect uniformity measurements. "
                  "Disable local dimming for flat-field calibration if possible."
        ),
        notes="Reference Mini-LED. 99% DCI-P3, 89% BT.2020. 1152 zones FALD. Source: TFTCentral/Rtings."
    )

    # MSI MEG 342C QD-OLED
    # Source: Hardware Unboxed, TFTCentral
    panels["MEG342C"] = PanelCharacterization(
        manufacturer="MSI",
        model_pattern=r"MEG.*342C|MSI.*342C.*QD.*OLED",
        panel_type="QD-OLED",
        display_name="MEG 342C QD-OLED",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6785, 0.3090),
            green=ChromaticityCoord(0.2335, 0.7105),
            blue=ChromaticityCoord(0.1380, 0.0508),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2040, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1975, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2015, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=250.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.0001,
            native_contrast=1000000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        notes="34-inch 3440x1440 QD-OLED ultrawide. Same panel family as G85SB. Source: HUB/TFTCentral."
    )

    # Corsair Xeneon 34 QD-OLED
    # Source: Rtings, Hardware Unboxed
    panels["XENEON34"] = PanelCharacterization(
        manufacturer="Corsair",
        model_pattern=r"Xeneon.*34|CM-9030002",
        panel_type="QD-OLED",
        display_name="Xeneon 34 QD-OLED",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6788, 0.3092),
            green=ChromaticityCoord(0.2332, 0.7102),
            blue=ChromaticityCoord(0.1378, 0.0505),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2035, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1980, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2010, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=260.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.0001,
            native_contrast=1000000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        notes="34-inch QD-OLED with iCUE integration. Same Samsung panel. Source: Rtings/HUB."
    )

    # Gigabyte AORUS FO32U2P (QD-OLED 4K 32")
    # Source: Hardware Unboxed
    panels["FO32U2P"] = PanelCharacterization(
        manufacturer="Gigabyte",
        model_pattern=r"FO32U2P|AORUS.*FO32U2",
        panel_type="QD-OLED",
        display_name="AORUS FO32U2P",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6790, 0.3095),
            green=ChromaticityCoord(0.2325, 0.7110),
            blue=ChromaticityCoord(0.1375, 0.0500),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2018, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1988, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2005, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=275.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        notes="32-inch 4K 240Hz QD-OLED. Same Samsung panel as PG32UCDM. Source: Hardware Unboxed."
    )

    # LG UltraGear OLED 27GR95QE (LG WOLED)
    panels["27GR95QE"] = PanelCharacterization(
        manufacturer="LG",
        model_pattern=r"27GR95QE|UltraGear.*27GR95",
        panel_type="WOLED",
        display_name="UltraGear OLED 27GR95QE",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6401, 0.3300),
            green=ChromaticityCoord(0.3000, 0.6000),
            blue=ChromaticityCoord(0.1500, 0.0600),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2010, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.1990, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=200.0,
            max_luminance_hdr=800.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        notes="LG WOLED panel. Similar to PG27UCDM with LG OSD and features."
    )

    # Sony INZONE M9 (IPS with Full-Array Local Dimming)
    panels["INZONE_M9"] = PanelCharacterization(
        manufacturer="Sony",
        model_pattern=r"INZONE.*M9|SDM-U27M90",
        panel_type="IPS",
        display_name="INZONE M9",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6465, 0.3340),
            green=ChromaticityCoord(0.2700, 0.6350),
            blue=ChromaticityCoord(0.1500, 0.0600),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2200, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2200, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2200, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=350.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.05,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=True,
            local_dimming_zones=96
        ),
        ddc=DDCRecommendations(
            picture_mode="Game 1",
            picture_mode_vcp=0x0B,
            color_preset="Custom",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Game 1 or Game 2 picture mode for full color control access. "
                  "Standard mode locks several color controls but has better default white balance. "
                  "Picture modes: Standard, FPS Game, Cinema, Game 1, Game 2. "
                  "DDC/CI accessible via OSD Others menu. Sony INZONE Hub app also provides control. "
                  "Color temperature presets: Warm, Neutral, Cool, Custom. "
                  "Gamma presets: 1.8, 2.0, 2.2, 2.4. Hue/saturation adjustments available. "
                  "Local dimming (96 zones FALD) should be set to Off for SDR calibration, "
                  "as it can cause brightness inconsistencies during measurement. "
                  "Each unit ships with individual factory calibration report."
        ),
        notes="IPS with FALD. Requires local dimming consideration for calibration."
    )

    # Samsung Odyssey G7 / G5 (VA curved ultrawide - 3440x1440)
    # Source: Rtings, TFTCentral measurements
    panels["ODYSSEY_G7_UW"] = PanelCharacterization(
        manufacturer="Samsung",
        model_pattern=r"SAM72F2|G7.*34|C34G5|Odyssey.*G7.*34|LC34G5",
        panel_type="VA",
        display_name="Odyssey G7 Ultrawide",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3310),
            green=ChromaticityCoord(0.2680, 0.6420),
            blue=ChromaticityCoord(0.1500, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2100, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2050, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2080, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=350.0,
            max_luminance_hdr=600.0,
            min_luminance=0.05,
            native_contrast=2500.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom",
            picture_mode_vcp=0x0B,
            color_preset="Custom",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=75,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="Mode1",
            gamma_vcp_value=0x04,
            notes="Use Custom picture mode for DDC/CI RGB gain access. "
                  "Disable Adaptive-Sync in OSD before DDC calibration to avoid comm drops. "
                  "sRGB mode clamps gamut but locks brightness/contrast controls. "
                  "Dynamic Brightness must be off. Eye Saver Mode must be off."
        ),
        notes="Samsung VA curved ultrawide. 125% sRGB gamut. Good contrast. Source: Rtings/TFTCentral."
    )

    # Dell U2723QE - 4K 60Hz IPS (sRGB professional)
    # Source: Rtings.com, TFTCentral measurements
    panels["U2723QE"] = PanelCharacterization(
        manufacturer="Dell",
        model_pattern=r"U2723QE|Dell.*U2723",
        panel_type="IPS",
        display_name="U2723QE",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6400, 0.3300),
            green=ChromaticityCoord(0.3000, 0.6000),
            blue=ChromaticityCoord(0.1500, 0.0600),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=350.0,
            max_luminance_hdr=350.0,
            min_luminance=0.25,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=False,
            wide_gamut=False,
            vrr_capable=False,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom Color",
            picture_mode_vcp=0x0B,
            color_preset="Custom Color",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=75,
            initial_contrast=75,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom Color mode for DDC/CI RGB gain access. "
                  "sRGB mode available but locks brightness/contrast/color controls. "
                  "ComfortView (low blue light) must be off. "
                  "Smart HDR not present on this model. USB-C connected - DDC works over USB-C DP Alt."
        ),
        notes="Factory calibrated sRGB IPS. Delta E < 2 out of box. USB-C hub monitor. Source: Rtings/TFTCentral."
    )

    # BenQ SW271C - 4K 60Hz IPS (Photo editing, 99% AdobeRGB)
    # Source: TFTCentral professional review
    panels["SW271C"] = PanelCharacterization(
        manufacturer="BenQ",
        model_pattern=r"SW271C|BenQ.*SW271C",
        panel_type="IPS",
        display_name="SW271C",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3320),
            green=ChromaticityCoord(0.2750, 0.6400),
            blue=ChromaticityCoord(0.1495, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=300.0,
            max_luminance_hdr=300.0,
            min_luminance=0.20,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=False,
            wide_gamut=True,
            vrr_capable=False,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom",
            picture_mode_vcp=0x0B,
            color_preset="Custom",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=60,
            initial_contrast=50,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom picture mode for DDC/CI RGB gain access. "
                  "Picture modes: Adobe RGB, sRGB, Rec.709, DCI-P3, Display P3, M-book, "
                  "B+W, HDR, Calibration 1/2/3, Custom, Paper Color Sync, DICOM. "
                  "Hardware calibration via Palette Master Ultimate is preferred over DDC/CI - "
                  "writes directly to internal 14-bit 3D LUT for superior accuracy. "
                  "Calibration 1/2/3 slots store hardware calibration profiles. "
                  "Color temp presets: 5000K, 6500K, 9300K, Custom, User Defined (100K increments). "
                  "Hotkey Puck G2 allows fast mode switching. USB-C one-cable calibration supported. "
                  "DDC/CI works but Palette Master Ultimate is the recommended path."
        ),
        notes="99% AdobeRGB photo editing monitor. Hardware calibration support. Delta E < 2. Source: TFTCentral."
    )

    # EIZO CG2700S - 2K 60Hz IPS (Professional reference)
    # Source: TFTCentral, EIZO published specifications
    panels["CG2700S"] = PanelCharacterization(
        manufacturer="EIZO",
        model_pattern=r"CG2700S|EIZO.*CG2700S|ColorEdge.*CG2700",
        panel_type="IPS",
        display_name="ColorEdge CG2700S",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3320),
            green=ChromaticityCoord(0.2750, 0.6400),
            blue=ChromaticityCoord(0.1495, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=300.0,
            max_luminance_hdr=300.0,
            min_luminance=0.20,
            native_contrast=1300.0,
            bit_depth=10,
            hdr_capable=False,
            wide_gamut=True,
            vrr_capable=False,
            local_dimming=False
        ),
        notes="Professional reference monitor. 99% AdobeRGB, built-in colorimeter. Delta E < 1. Source: TFTCentral."
    )

    # Dell U3423WE - 3440x1440 60Hz IPS (Ultrawide professional, 98% DCI-P3)
    # Source: Rtings.com measurements
    panels["U3423WE"] = PanelCharacterization(
        manufacturer="Dell",
        model_pattern=r"U3423WE|Dell.*U3423",
        panel_type="IPS",
        display_name="U3423WE",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3320),
            green=ChromaticityCoord(0.2750, 0.6400),
            blue=ChromaticityCoord(0.1495, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=350.0,
            max_luminance_hdr=350.0,
            min_luminance=0.25,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=False,
            wide_gamut=True,
            vrr_capable=False,
            local_dimming=False
        ),
        notes="Ultrawide professional IPS. 98% DCI-P3. USB-C hub. Factory calibrated. Source: Rtings."
    )

    # ASUS VG27AQ1A - 2K 170Hz IPS (Gaming, 130% sRGB)
    # Source: Rtings.com, Hardware Unboxed
    panels["VG27AQ1A"] = PanelCharacterization(
        manufacturer="ASUS",
        model_pattern=r"VG27AQ1A|ASUS.*VG27AQ1A",
        panel_type="IPS",
        display_name="TUF Gaming VG27AQ1A",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3320),
            green=ChromaticityCoord(0.2750, 0.6400),
            blue=ChromaticityCoord(0.1495, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2100, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2050, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2080, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=350.0,
            max_luminance_hdr=400.0,
            min_luminance=0.10,
            native_contrast=1000.0,
            bit_depth=8,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        notes="Gaming IPS with 130% sRGB coverage. ELMB Sync. HDR400. Source: Rtings/Hardware Unboxed."
    )

    # Samsung Odyssey G7 27" - 2K 240Hz VA (Gaming, curved)
    # Source: Rtings.com, TFTCentral measurements
    panels["ODYSSEY_G7_27"] = PanelCharacterization(
        manufacturer="Samsung",
        model_pattern=r"C27G7|LC27G7|Odyssey.*G7.*27|G7.*27",
        panel_type="VA",
        display_name="Odyssey G7 27\"",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3310),
            green=ChromaticityCoord(0.2680, 0.6420),
            blue=ChromaticityCoord(0.1500, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2120, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2060, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2090, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=350.0,
            max_luminance_hdr=600.0,
            min_luminance=0.05,
            native_contrast=2500.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom",
            picture_mode_vcp=0x0B,
            color_preset="Custom",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=75,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="Mode1",
            gamma_vcp_value=0x04,
            notes="Use Custom picture mode for DDC/CI RGB gain access. "
                  "Disable Adaptive-Sync in OSD before DDC calibration to avoid comm drops. "
                  "sRGB mode available but locks out adjustments. "
                  "Dynamic Brightness and Eye Saver Mode must be off."
        ),
        notes="VA curved 1000R gaming monitor. 125% sRGB, HDR600. Source: Rtings/TFTCentral."
    )

    # LG 27GP850-B - 2K 165Hz Nano IPS (Gaming, 98% DCI-P3)
    # Source: Rtings.com, TFTCentral measurements
    panels["27GP850"] = PanelCharacterization(
        manufacturer="LG",
        model_pattern=r"27GP850|UltraGear.*27GP850",
        panel_type="Nano-IPS",
        display_name="UltraGear 27GP850-B",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3320),
            green=ChromaticityCoord(0.2750, 0.6400),
            blue=ChromaticityCoord(0.1495, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2100, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2050, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2080, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=350.0,
            max_luminance_hdr=400.0,
            min_luminance=0.08,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        notes="Nano IPS with 98% DCI-P3. 165Hz gaming. HDR400. Source: Rtings/TFTCentral."
    )

    # Dell S2722DGM - 2K 165Hz VA (Budget gaming)
    # Source: Rtings.com measurements
    panels["S2722DGM"] = PanelCharacterization(
        manufacturer="Dell",
        model_pattern=r"S2722DGM|Dell.*S2722DGM",
        panel_type="VA",
        display_name="S2722DGM",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6400, 0.3300),
            green=ChromaticityCoord(0.3000, 0.6000),
            blue=ChromaticityCoord(0.1500, 0.0600),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2150, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2100, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2120, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=300.0,
            max_luminance_hdr=400.0,
            min_luminance=0.05,
            native_contrast=3000.0,
            bit_depth=8,
            hdr_capable=False,
            wide_gamut=False,
            vrr_capable=True,
            local_dimming=False
        ),
        notes="Budget VA gaming monitor. ~99% sRGB. 165Hz curved. Source: Rtings."
    )

    # Sony A95L - 4K 120Hz QD-OLED TV
    # Source: Rtings.com, HDTVTest
    panels["SONY_A95L"] = PanelCharacterization(
        manufacturer="Sony",
        model_pattern=r"A95L|XR.*A95L|BRAVIA.*A95L",
        panel_type="QD-OLED",
        display_name="BRAVIA A95L",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6795, 0.3095),
            green=ChromaticityCoord(0.2325, 0.7115),
            blue=ChromaticityCoord(0.1375, 0.0495),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2020, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1985, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2005, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=250.0,
            max_luminance_hdr=1400.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        notes="Sony QD-OLED TV with Samsung Display panel. Excellent processing. Source: Rtings/HDTVTest."
    )

    # Samsung S95D - 4K 144Hz QD-OLED TV
    # Source: Rtings.com, HDTVTest
    panels["S95D"] = PanelCharacterization(
        manufacturer="Samsung",
        model_pattern=r"S95D|QE.*S95D|QN.*S95D",
        panel_type="QD-OLED",
        display_name="S95D QD-OLED",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6792, 0.3098),
            green=ChromaticityCoord(0.2318, 0.7108),
            blue=ChromaticityCoord(0.1372, 0.0498),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2010, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1990, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=260.0,
            max_luminance_hdr=1500.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        notes="2024 Samsung QD-OLED TV with anti-glare. 144Hz VRR. Source: Rtings/HDTVTest."
    )

    # ASUS PG34WCDM - 3440x1440 240Hz WOLED (Ultrawide)
    # Source: TFTCentral review - confirmed LG.Display WOLED panel
    panels["PG34WCDM"] = PanelCharacterization(
        manufacturer="ASUS",
        model_pattern=r"PG34WCDM|ROG.*PG34WCDM|PG34.*WCDM",
        panel_type="WOLED",
        display_name="ROG Swift OLED PG34WCDM",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6400, 0.3300),
            green=ChromaticityCoord(0.3000, 0.6000),
            blue=ChromaticityCoord(0.1500, 0.0600),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2015, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1990, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2005, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=275.0,
            max_luminance_hdr=1300.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom 1",
            picture_mode_vcp=0x0B,
            color_preset="User",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=40,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom 1 picture mode for unlocked RGB gain controls. "
                  "LG.Display WOLED panel (NOT QD-OLED). 800R curvature ultrawide. "
                  "Disable ELMB Sync for stable DDC communication. "
                  "sRGB emulation available via OSD preset. "
                  "OSD gamma options: 1.8, 2.0, 2.2, 2.4, 2.6. "
                  "VRR (Adaptive-Sync) can remain on. Uniform Brightness recommended off."
        ),
        notes="34-inch 3440x1440 240Hz WOLED ultrawide. LG.Display panel (first 34\" WOLED). "
              "98% DCI-P3, 95.5% Adobe RGB. 800R curve. Source: TFTCentral."
    )

    # Gigabyte M28U - 4K 144Hz IPS (Budget 4K gaming)
    # Source: Rtings.com, Hardware Unboxed
    panels["M28U"] = PanelCharacterization(
        manufacturer="Gigabyte",
        model_pattern=r"M28U|GIGABYTE.*M28U",
        panel_type="IPS",
        display_name="M28U",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3320),
            green=ChromaticityCoord(0.2750, 0.6400),
            blue=ChromaticityCoord(0.1495, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2100, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2050, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2080, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=300.0,
            max_luminance_hdr=400.0,
            min_luminance=0.10,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        notes="Budget 4K 144Hz IPS gaming. 90% DCI-P3. HDMI 2.1. Source: Rtings/Hardware Unboxed."
    )

    # ViewSonic VP2786-4K - 4K 60Hz IPS (Professional)
    # Source: TFTCentral, Rtings
    panels["VP2786"] = PanelCharacterization(
        manufacturer="ViewSonic",
        model_pattern=r"VP2786|ViewSonic.*VP2786",
        panel_type="IPS",
        display_name="VP2786-4K",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3320),
            green=ChromaticityCoord(0.2750, 0.6400),
            blue=ChromaticityCoord(0.1495, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=350.0,
            max_luminance_hdr=350.0,
            min_luminance=0.25,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=False,
            wide_gamut=True,
            vrr_capable=False,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom",
            picture_mode_vcp=0x0B,
            color_preset="User",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=60,
            initial_contrast=50,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom picture mode for DDC/CI RGB gain access. "
                  "Picture modes: sRGB, Adobe RGB, DCI-P3, Rec.709, DICOM, Custom, User. "
                  "Hardware calibration via Colorbration+ software (ViewSonic's calibration tool). "
                  "Dual color engine allows different presets in PIP/PBP mode. "
                  "ColorPro Wheel provides integrated color calibration workflow. "
                  "Color temp: 5000K, 6500K, 7500K, 9300K, User Defined. "
                  "DDC/CI brightness control confirmed but 1ms Mode disables DDC/CI brightness. "
                  "Pantone Validated, Fogra certified. USB-C 90W PD. "
                  "Advanced DCR (dynamic contrast) must be off for calibration."
        ),
        notes="Professional 4K IPS. 100% sRGB, 98% DCI-P3, factory calibrated Delta E < 2. USB-C. Source: TFTCentral/Rtings."
    )

    # LG 32GS95UE - 4K 240Hz WOLED 32"
    # Source: Rtings.com, Hardware Unboxed
    panels["32GS95UE"] = PanelCharacterization(
        manufacturer="LG",
        model_pattern=r"32GS95UE|UltraGear.*32GS95",
        panel_type="WOLED",
        display_name="UltraGear OLED 32GS95UE",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6398, 0.3302),
            green=ChromaticityCoord(0.2999, 0.5997),
            blue=ChromaticityCoord(0.1501, 0.0602),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2008, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1995, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2002, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=275.0,
            max_luminance_hdr=900.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        notes="32-inch 4K 240Hz WOLED monitor. Similar to LG C4 primaries. Source: Rtings/Hardware Unboxed."
    )

    # MSI MAG 274QRF-QD - 2K 165Hz Quantum Dot IPS
    # Source: Rtings.com, Hardware Unboxed
    panels["274QRF_QD"] = PanelCharacterization(
        manufacturer="MSI",
        model_pattern=r"274QRF.*QD|MAG.*274QRF|MSI.*274QRF",
        panel_type="IPS",
        display_name="MAG 274QRF QD",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3320),
            green=ChromaticityCoord(0.2750, 0.6400),
            blue=ChromaticityCoord(0.1495, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2080, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2040, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2060, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=350.0,
            max_luminance_hdr=400.0,
            min_luminance=0.08,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        notes="QD-enhanced IPS with ~97% DCI-P3. Excellent color for gaming. Source: Rtings/Hardware Unboxed."
    )

    # BenQ PD2706U - 4K 60Hz IPS (Professional, 99% sRGB)
    # Source: TFTCentral, Rtings.com measurements
    panels["PD2706U"] = PanelCharacterization(
        manufacturer="BenQ",
        model_pattern=r"PD2706U|BenQ.*PD2706",
        panel_type="IPS",
        display_name="DesignVue PD2706U",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6400, 0.3300),
            green=ChromaticityCoord(0.3000, 0.6000),
            blue=ChromaticityCoord(0.1500, 0.0600),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=350.0,
            max_luminance_hdr=350.0,
            min_luminance=0.25,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=False,
            wide_gamut=False,
            vrr_capable=False,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom 1",
            picture_mode_vcp=0x0B,
            color_preset="User",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=70,
            initial_contrast=50,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom 1 or Custom 2 picture mode for DDC/CI RGB gain access. "
                  "sRGB mode locks all controls - avoid for DDC calibration. "
                  "Disable B.I.+ (Brightness Intelligence Plus) auto-brightness sensor. "
                  "Disable auto-dimming/eco mode. Display Pilot software can conflict with DDC. "
                  "Color modes: Custom 1, Custom 2, sRGB, Rec.709, DICOM, Darkroom, M-Book, User."
        ),
        notes="Professional 4K IPS with 99% sRGB, factory calibrated Delta E < 3. USB-C 90W. Source: TFTCentral/Rtings."
    )

    # EIZO CS2740 - 4K 60Hz IPS (Professional, hardware calibration via ColorNavigator)
    # Source: TFTCentral, EIZO published specifications
    panels["CS2740"] = PanelCharacterization(
        manufacturer="EIZO",
        model_pattern=r"CS2740|EIZO.*CS2740|ColorEdge.*CS2740",
        panel_type="IPS",
        display_name="ColorEdge CS2740",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3320),
            green=ChromaticityCoord(0.2750, 0.6400),
            blue=ChromaticityCoord(0.1495, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=350.0,
            max_luminance_hdr=350.0,
            min_luminance=0.20,
            native_contrast=1300.0,
            bit_depth=10,
            hdr_capable=False,
            wide_gamut=True,
            vrr_capable=False,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="User",
            picture_mode_vcp=0x0B,
            color_preset="User",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=60,
            initial_contrast=50,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use User color mode for DDC/CI access. EIZO supports hardware LUT calibration "
                  "via ColorNavigator 7 - this is preferred over DDC/CI for this monitor. "
                  "Built-in calibration sensor (SelfCalibration on schedule) on CG series, not CS. "
                  "DDC/CI works but ColorNavigator provides direct 16-bit 3D LUT access. "
                  "Eco mode and Auto EcoView must be disabled for stable brightness."
        ),
        notes="Professional 4K IPS. 99% AdobeRGB. Hardware LUT calibration via ColorNavigator. Delta E < 2. Source: TFTCentral."
    )

    # ASUS ProArt PA279CRV - 4K 60Hz IPS (Professional, 99% DCI-P3)
    # Source: ASUS specs, DisplayNinja review, TFTCentral
    panels["PA279CRV"] = PanelCharacterization(
        manufacturer="ASUS",
        model_pattern=r"PA279CRV|ProArt.*PA279CRV",
        panel_type="IPS",
        display_name="ProArt PA279CRV",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3320),
            green=ChromaticityCoord(0.2750, 0.6400),
            blue=ChromaticityCoord(0.1495, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=350.0,
            max_luminance_hdr=400.0,
            min_luminance=0.20,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=False,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="User Mode 1",
            picture_mode_vcp=0x0B,
            color_preset="User",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=60,
            initial_contrast=50,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use User Mode 1 or User Mode 2 for DDC/CI RGB gain access. "
                  "Picture modes: Native, sRGB, Adobe RGB, DCI-P3, Rec.2020, DICOM, "
                  "Rec.709, HDR (PQ Optimized/PQ Clip/PQ Basic), User Mode 1, User Mode 2. "
                  "Color temp presets: 9300K, 6500K, 5500K, 5000K, P3-Theater (DCI-P3 only). "
                  "Gamma options: 1.8, 2.0, 2.2, 2.4, 2.6. "
                  "RGB gain and offset adjustable in most presets. "
                  "ProArt Calibration software stores profiles to User Mode 1/2. "
                  "ASUS DisplayWidget Center app provides DDC/CI desktop control. "
                  "Calman Verified with Delta E < 2 factory calibration."
        ),
        notes="Professional 4K IPS. 99% DCI-P3, 99% Adobe RGB, 100% sRGB. Calman Verified. USB-C 96W PD. Source: ASUS/DisplayNinja."
    )

    # MSI MPG 321URX QD-OLED - 4K 240Hz QD-OLED
    # Source: TFTCentral, Rtings.com, KitGuru review
    panels["MPG321URX"] = PanelCharacterization(
        manufacturer="MSI",
        model_pattern=r"MPG.*321URX|MAG.*321URX|MSI.*321URX|321URX",
        panel_type="QD-OLED",
        display_name="MPG 321URX QD-OLED",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6795, 0.3095),
            green=ChromaticityCoord(0.2325, 0.7115),
            blue=ChromaticityCoord(0.1375, 0.0495),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2020, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1985, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2005, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=275.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="User",
            picture_mode_vcp=0x0B,
            color_preset="Custom",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=45,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use User mode for DDC/CI RGB gain access. "
                  "Default mode is Eco which caps brightness - switch to User for full control. "
                  "Gaming color modes: 6 modes (less accurate, oversaturated). "
                  "Professional modes: sRGB (recommended for accurate work), DCI-P3, Adobe RGB. "
                  "sRGB mode provides excellent out-of-box accuracy (dE ~0.33 after calibration). "
                  "HDR modes: HDR 400 True Black (450 nits cap), Peak 1000 (full 1000 nits). "
                  "DDC/CI works via ControlMyMonitor and similar tools. "
                  "OSD via joystick toggle behind MSI logo. "
                  "Color temp presets: Warm, Normal, Cool, Custom."
        ),
        notes="32-inch 4K 240Hz QD-OLED. Samsung 2024 panel. 99% DCI-P3. Source: TFTCentral/Rtings/KitGuru."
    )

    # LG C2 OLED (WOLED TV used as monitor - 42/48/55/65 inch)
    # Source: Rtings.com, HDTVTest, TFTCentral calibration guide
    panels["LG_C2"] = PanelCharacterization(
        manufacturer="LG",
        model_pattern=r"OLED42C2|OLED48C2|OLED55C2|OLED65C2|LG.*C2|OLED.*C2",
        panel_type="WOLED",
        display_name="C2 OLED",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6399, 0.3301),
            green=ChromaticityCoord(0.2998, 0.5998),
            blue=ChromaticityCoord(0.1502, 0.0601),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=170.0,
            max_luminance_hdr=750.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Game Optimizer",
            picture_mode_vcp=0x0B,
            color_preset="Warm 50",
            color_preset_vcp=0x05,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=85,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="BT.1886",
            gamma_vcp_value=0x08,
            notes="WARNING: LG C2 has limited DDC/CI support - brightness control may not work via DDC. "
                  "Use Game Optimizer or ISF Expert (Dark Room) for calibration. "
                  "Picture modes: Vivid, Standard, Cinema, Cinema Home, Sports, "
                  "Game Optimizer, Filmmaker, ISF Expert (Bright), ISF Expert (Dark). "
                  "Disable AI Brightness (AI Picture Pro) - it overrides DDC brightness. "
                  "Disable ASBL (Auto Static Brightness Limiter) via service menu if possible. "
                  "Enable HDMI ULTRA HD Deep Color for 10-bit. Set HDMI input label to PC. "
                  "Color temp presets: Warm 50 (D65), Warm 30, Medium, Cool. "
                  "White Balance submenu provides 2-point and 20-point adjustment. "
                  "Professional calibration via Calman AutoCal requires network connection. "
                  "For Calman DDC, select '2021 Alpha 9' pattern. "
                  "OLED Shadow Detail adjustable (start at 23/200). "
                  "SDR ISF Expert Dark recommended with ALLM Off for movies."
        ),
        notes="LG WOLED evo panel (2022). ~99% sRGB, ~97% DCI-P3. Excellent for gaming. Source: Rtings/HDTVTest."
    )

    # Dell S2722QC - 4K 60Hz IPS (Budget USB-C)
    # Source: Rtings.com, PC Monitors review
    panels["S2722QC"] = PanelCharacterization(
        manufacturer="Dell",
        model_pattern=r"S2722QC|Dell.*S2722QC",
        panel_type="IPS",
        display_name="S2722QC",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6400, 0.3300),
            green=ChromaticityCoord(0.3000, 0.6000),
            blue=ChromaticityCoord(0.1500, 0.0600),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2100, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2050, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2080, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=300.0,
            max_luminance_hdr=400.0,
            min_luminance=0.20,
            native_contrast=1000.0,
            bit_depth=8,
            hdr_capable=True,
            wide_gamut=False,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom Color",
            picture_mode_vcp=0x0B,
            color_preset="Custom Color",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=75,
            initial_contrast=75,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom Color mode for DDC/CI RGB gain access. "
                  "Enable DDC/CI in Others menu. Dell Display Manager provides desktop control. "
                  "Picture modes: Standard, Custom Color, Movie, Game, Warm, Cool, Color Temp. "
                  "Smart HDR modes (when HDR signal detected): Desktop, Movie HDR, Game HDR. "
                  "sRGB preset locks brightness/contrast/color controls - avoid for DDC calibration. "
                  "ComfortView (low blue light) must be off. "
                  "RGB gain steps are coarse - a change of 1 noticeably shifts color. "
                  "USB-C connected - DDC works over USB-C DP Alt mode. "
                  "97% sRGB, 88% DCI-P3 coverage."
        ),
        notes="Budget 4K IPS USB-C monitor. 97% sRGB, 88% DCI-P3. 65W USB-C PD. Source: Rtings/PC Monitors."
    )

    # Corsair Xeneon 27QHD240 OLED - 1440p 240Hz WOLED
    # Source: Tom's Hardware, Rtings.com, KitGuru review
    panels["XENEON27QHD240"] = PanelCharacterization(
        manufacturer="Corsair",
        model_pattern=r"Xeneon.*27QHD240|CM-9030002|27QHD240",
        panel_type="WOLED",
        display_name="Xeneon 27QHD240 OLED",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6398, 0.3302),
            green=ChromaticityCoord(0.2999, 0.5997),
            blue=ChromaticityCoord(0.1501, 0.0602),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2010, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1995, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2005, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=250.0,
            max_luminance_hdr=800.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Standard",
            picture_mode_vcp=0x0B,
            color_preset="Custom",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=45,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Standard picture mode for full RGB gain/offset access with native gamut. "
                  "Picture modes: Standard, Movie, Text, sRGB, Creative, Game, HDR. "
                  "Standard mode is fully adjustable with native wide gamut. "
                  "sRGB mode clamps gamut but has independent color temp and gamma options. "
                  "HDR mode is non-adjustable. "
                  "Color temp and gamma independently adjustable per mode. "
                  "OSD via joystick press/navigate. iCUE integration available. "
                  "Orbit pixel-shift (1px/min) always active for burn-in prevention. "
                  "Image Retention Refresh runs automatically every 8 hours. "
                  "LG Display 3rd-gen WOLED panel. ~96% DCI-P3, 100% sRGB."
        ),
        notes="27-inch 1440p 240Hz WOLED. LG Display 3rd-gen panel. 96% DCI-P3, 100% sRGB. Source: Tom's HW/Rtings/KitGuru."
    )

    # Gigabyte M32U - 4K 144Hz IPS (Gaming)
    # Source: PC Monitors, Rtings.com, Display Ninja review
    panels["M32U"] = PanelCharacterization(
        manufacturer="Gigabyte",
        model_pattern=r"M32U|GIGABYTE.*M32U",
        panel_type="IPS",
        display_name="M32U",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3320),
            green=ChromaticityCoord(0.2750, 0.6400),
            blue=ChromaticityCoord(0.1495, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2100, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2050, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2080, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=300.0,
            max_luminance_hdr=400.0,
            min_luminance=0.10,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom 1",
            picture_mode_vcp=0x0B,
            color_preset="User Define",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=50,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom 1/2/3 picture mode for DDC/CI RGB gain access. "
                  "Picture modes: Standard, FPS, RTS/RPG, Movie, Reader, sRGB, Custom 1/2/3. "
                  "sRGB mode locks most settings including gamma, overdrive, and color channels. "
                  "Custom modes are identical to Standard by default with separate settings memory. "
                  "Color temp: Warm, Normal, Cool, User Define (RGB gain sliders). "
                  "Gamma options: 1.8 (Off), 2.0, 2.2, 2.4, 2.6. "
                  "OSD Sidekick desktop app provides DDC/CI control via Realtek scaler. "
                  "sRGB mode restricts gamut to ~100% sRGB. Native is ~87-90% DCI-P3. "
                  "Aim Stabilizer Sync and Smart OD locked in sRGB mode."
        ),
        notes="32-inch 4K 144Hz IPS gaming. 90% DCI-P3, 100% sRGB. HDMI 2.1. Source: PC Monitors/Rtings/Display Ninja."
    )

    # HP Z27k G3 - 4K 60Hz IPS (USB-C Professional)
    # Source: HP specs, StorageReview, MonitorNerds review
    panels["Z27K_G3"] = PanelCharacterization(
        manufacturer="HP",
        model_pattern=r"Z27k.*G3|HP.*Z27k|1B9T0",
        panel_type="IPS",
        display_name="Z27k G3 4K USB-C",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6400, 0.3300),
            green=ChromaticityCoord(0.3000, 0.6000),
            blue=ChromaticityCoord(0.1500, 0.0600),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=350.0,
            max_luminance_hdr=350.0,
            min_luminance=0.25,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=False,
            wide_gamut=False,
            vrr_capable=False,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom RGB",
            picture_mode_vcp=0x0B,
            color_preset="Custom RGB",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=65,
            initial_contrast=50,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom RGB mode for DDC/CI RGB gain access. "
                  "Picture presets: sRGB, BT.709, P3 D65 (post-Jan 2021 units), Custom RGB. "
                  "DDC/CI can be toggled on/off in Management menu of OSD. "
                  "HP Display Center software provides desktop display management. "
                  "Factory calibrated Delta E <= 2. PANTONE Validated. "
                  "User-assignable function buttons on OSD. "
                  "99% sRGB, 85% DCI-P3 coverage. 100W USB-C PD. "
                  "4-port USB-C hub built in. "
                  "sRGB and BT.709 modes lock color adjustments - use Custom RGB for calibration."
        ),
        notes="Professional 4K IPS. 99% sRGB, 85% DCI-P3. PANTONE Validated. 100W USB-C PD. Source: HP/StorageReview."
    )

    # Samsung Odyssey OLED G6 G60SD (Samsung QD-OLED 27" 1440p 360Hz - 2024)
    # Source: Rtings.com, TFTCentral, Tom's Hardware
    panels["G60SD"] = PanelCharacterization(
        manufacturer="Samsung",
        model_pattern=r"G60SD|S27DG60|Odyssey.*G60SD|Odyssey.*OLED.*G6|LS27DG60",
        panel_type="QD-OLED",
        display_name="Odyssey OLED G6 G60SD",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6790, 0.3095),
            green=ChromaticityCoord(0.2325, 0.7110),
            blue=ChromaticityCoord(0.1375, 0.0498),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2020, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1985, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2005, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=250.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom",
            picture_mode_vcp=0x0B,
            color_preset="Custom",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=45,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="WARNING: Samsung DDC/CI works over HDMI only - does NOT work over DisplayPort. "
                  "Use Custom picture mode for RGB gain access. "
                  "3rd gen Samsung QD-OLED with matte AG coating and heat-pipe cooling. "
                  "Dynamic Brightness must be off. Eye Saver Mode must be off. "
                  "Color temp presets: Custom, Warm, Normal, Cool. "
                  "Game mode and Adaptive-Sync should be disabled during calibration."
        ),
        notes="27-inch 1440p 360Hz QD-OLED. 3rd gen Samsung panel. 99% DCI-P3. "
              "Matte AG coating. Source: Rtings/TFTCentral/Tom's Hardware."
    )

    # ASUS ROG Swift PG27AQDP (LG WOLED 27" 1440p 480Hz - 2024)
    # Source: TFTCentral review
    panels["PG27AQDP"] = PanelCharacterization(
        manufacturer="ASUS",
        model_pattern=r"PG27AQDP|ROG.*PG27AQDP|PG27.*AQDP",
        panel_type="WOLED",
        display_name="ROG Swift OLED PG27AQDP",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6400, 0.3300),
            green=ChromaticityCoord(0.3000, 0.6000),
            blue=ChromaticityCoord(0.1500, 0.0600),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2010, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1995, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2005, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=255.0,
            max_luminance_hdr=1300.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom 1",
            picture_mode_vcp=0x0B,
            color_preset="User",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=40,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom 1 picture mode for unlocked RGB gain controls. "
                  "LG.Display WOLED panel - NOT QD-OLED. 480Hz native refresh rate. "
                  "Disable ELMB Sync for stable DDC communication. "
                  "OSD gamma options: 1.8, 2.0, 2.2, 2.4, 2.6. "
                  "HDR peak 1300 nits spec, 425 nits measured SDR max variable APL. "
                  "Custom heatsink cooling (fanless). VRR can remain on."
        ),
        notes="27-inch 1440p 480Hz WOLED. LG.Display latest gen panel. ~125% sRGB. "
              "VESA DisplayHDR True Black 400. Source: TFTCentral."
    )

    # Dell Alienware AW2725DF (Samsung QD-OLED 27" 1440p 360Hz - 2024)
    # Source: TFTCentral review, Rtings
    panels["AW2725DF"] = PanelCharacterization(
        manufacturer="Dell",
        model_pattern=r"AW2725DF|Alienware.*2725DF|AW2725",
        panel_type="QD-OLED",
        display_name="Alienware AW2725DF",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6792, 0.3098),
            green=ChromaticityCoord(0.2320, 0.7108),
            blue=ChromaticityCoord(0.1372, 0.0498),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2015, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1990, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2005, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=268.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom Color",
            picture_mode_vcp=0x0B,
            color_preset="Custom Color",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=45,
            initial_contrast=75,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom Color mode for full DDC/CI RGB gain access. "
                  "3rd gen Samsung QD-OLED panel. First mainstream 27\" QD-OLED from Dell. "
                  "Enable DDC/CI in Others menu. No hardware calibration support. "
                  "Gamma options: 2.2, 2.4, sRGB, BT.1886, PQ. "
                  "Factory calibrated DeltaE <2 for sRGB and DCI-P3. "
                  "ComfortView Plus (low blue light) must be off. "
                  "Dark Stabilizer manipulates gamma - disable for calibration. "
                  "Connectivity: 2x DP 1.4, 1x HDMI (limited bandwidth). "
                  "Dell Display Manager works over DP and HDMI."
        ),
        notes="27-inch 1440p 360Hz QD-OLED. 3rd gen Samsung panel. 99.3% DCI-P3. "
              "Factory calibrated. Source: TFTCentral/Rtings."
    )

    # Samsung Odyssey OLED G8 G81SD (Samsung QD-OLED 32" 4K - 2024 variant)
    # Source: Samsung.com - alternate SKU of G80SD
    panels["G81SD"] = PanelCharacterization(
        manufacturer="Samsung",
        model_pattern=r"G81SD|LS32DG81|Odyssey.*G81SD",
        panel_type="QD-OLED",
        display_name="Odyssey OLED G8 G81SD",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6785, 0.3095),
            green=ChromaticityCoord(0.2330, 0.7105),
            blue=ChromaticityCoord(0.1375, 0.0505),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2010, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1995, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2005, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=250.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom",
            picture_mode_vcp=0x0B,
            color_preset="Custom",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=45,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="WARNING: Samsung DDC/CI works over HDMI only - does NOT work over DisplayPort. "
                  "Use Custom picture mode for DDC/CI RGB gain access. "
                  "Same Samsung QD-OLED panel as G80SD (regional SKU variant). "
                  "Disable Game Mode and Adaptive-Sync during calibration for stable DDC. "
                  "Dynamic Brightness must be off. Core Lighting sync may interfere. "
                  "Glare Free matte coating. NQ8 AI Gen3 processor (Smart TV features). "
                  "Color temp presets: Custom, Warm, Normal, Cool."
        ),
        notes="32-inch 4K 240Hz QD-OLED. Same panel as G80SD (regional/SKU variant). "
              "99% DCI-P3. Matte AG coating. Source: Samsung.com/Rtings."
    )

    # LG G4 OLED (2024 WOLED evo with MLA - TV used as monitor)
    # Source: Rtings.com, HDTVTest, FlatpanelsHD
    panels["LG_G4"] = PanelCharacterization(
        manufacturer="LG",
        model_pattern=r"OLED55G4|OLED65G4|OLED77G4|OLED83G4|OLED97G4|LG.*G4.*OLED|G4.*SUB|G4.*WUA",
        panel_type="WOLED",
        display_name="G4 OLED evo",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6398, 0.3302),
            green=ChromaticityCoord(0.2999, 0.5997),
            blue=ChromaticityCoord(0.1501, 0.0602),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2005, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1998, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2002, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=257.0,
            max_luminance_hdr=1500.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Filmmaker",
            picture_mode_vcp=0x0B,
            color_preset="Warm 50",
            color_preset_vcp=0x05,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=85,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="BT.1886",
            gamma_vcp_value=0x08,
            notes="Use Filmmaker or Game Optimizer mode for DDC/CI access. "
                  "MLA (Micro Lens Array) panel with significantly higher brightness than C4. "
                  "1489 nits measured at 10% window, 1483 nits at 2% window. "
                  "Disable AI Brightness (AI Picture Pro) as it overrides DDC brightness. "
                  "Disable ASBL via service menu if possible for stable luminance. "
                  "Enable HDMI ULTRA HD Deep Color for 10-bit. Set HDMI label to PC. "
                  "Color temp presets: Warm 50, Warm 30, Medium, Cool. Use Warm 50 for D65. "
                  "97.4% DCI-P3, 72.9% BT.2020 measured coverage."
        ),
        notes="2024 LG WOLED evo with MLA for higher brightness. Flagship TV as monitor. "
              "97.4% DCI-P3, 72.9% BT.2020. Source: Rtings/HDTVTest/FlatpanelsHD."
    )

    # LG UltraGear OLED 34GS95QE (LG WOLED 34" 1440p 240Hz ultrawide)
    # Source: Rtings.com, TFTCentral, DisplayNinja
    panels["34GS95QE"] = PanelCharacterization(
        manufacturer="LG",
        model_pattern=r"34GS95QE|UltraGear.*34GS95|LG.*34GS95",
        panel_type="WOLED",
        display_name="UltraGear OLED 34GS95QE",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6400, 0.3300),
            green=ChromaticityCoord(0.3000, 0.6000),
            blue=ChromaticityCoord(0.1500, 0.0600),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2010, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1995, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2005, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=267.0,
            max_luminance_hdr=1300.0,
            min_luminance=0.0001,
            native_contrast=1500000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Gamer 1",
            picture_mode_vcp=0x0B,
            color_preset="Custom",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="Mode 3",
            gamma_vcp_value=0x04,
            notes="Use Gamer 1 or Gamer 2 for DDC/CI RGB gain access. "
                  "LG.Display 2nd gen WOLED panel. 800R curvature. "
                  "Supports hardware calibration (LG unique in OLED monitor market). "
                  "LG Calibration Studio stores profiles to Calibration 1/2 slots. "
                  "Gamma modes: Mode 1 (2.0), Mode 2 (2.2), Mode 3 (2.4), Mode 4 (2.6). "
                  "Color temp: Custom, 6500K, 7500K, 9300K. 6-axis hue/sat available. "
                  "FreeSync Premium Pro and G-sync Compatible certified. "
                  "HDR measured: 957 nits (1% window), 886 nits (4%), 778 nits (10%). "
                  "On-Screen Control app provides DDC/CI access from desktop."
        ),
        notes="34-inch 3440x1440 240Hz WOLED ultrawide. LG.Display 2nd gen panel. "
              "99% DCI-P3. 800R curve. Hardware calibration supported. Source: Rtings/TFTCentral."
    )

    # Apple Pro Display XDR (IPS LCD Mini-LED 32" 6K reference monitor)
    # Source: Apple Support tech specs
    panels["PRO_DISPLAY_XDR"] = PanelCharacterization(
        manufacturer="Apple",
        model_pattern=r"Pro.*Display.*XDR|Apple.*XDR|APPA044|A1999",
        panel_type="Mini-LED",
        display_name="Pro Display XDR",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6800, 0.3200),
            green=ChromaticityCoord(0.2650, 0.6900),
            blue=ChromaticityCoord(0.1500, 0.0600),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=500.0,
            max_luminance_hdr=1600.0,
            min_luminance=0.005,
            native_contrast=1000000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=False,
            local_dimming=True,
            local_dimming_zones=576
        ),
        ddc=DDCRecommendations(
            picture_mode="Pro Display XDR (P3-1600 nits)",
            picture_mode_vcp=None,
            color_preset="P3 D65",
            color_preset_vcp=None,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=None,
            notes="WARNING: Apple Pro Display XDR does NOT support standard DDC/CI for calibration. "
                  "Calibration is done through macOS reference modes and Apple's Pro Display Calibrator. "
                  "Reference modes: Pro Display XDR (P3-1600 nits), HDR Video, Digital Cinema, "
                  "Design and Print, sRGB, Photography. "
                  "Full Calibration requires compatible spectroradiometer. "
                  "Visual Fine Tune for quick adjustments to match other displays. "
                  "Apple-designed TCON chip controls 576 FALD zones. "
                  "6016x3384 resolution (6K) at 218 PPI. Oxide TFT IPS LCD. "
                  "Standard and Nano-texture glass options. Max 60Hz refresh."
        ),
        notes="Apple reference Mini-LED monitor. 6K resolution. P3 wide color. "
              "576 FALD zones. 1000 nits sustained, 1600 nits peak HDR. "
              "No standard DDC/CI - uses macOS reference modes. Source: Apple Support."
    )

    # ASUS ProArt PA32UCXR (Mini-LED 32" 4K reference with built-in colorimeter)
    # Source: Tom's Hardware review, ASUS specs, PCMonitors
    panels["PA32UCXR"] = PanelCharacterization(
        manufacturer="ASUS",
        model_pattern=r"PA32UCXR|ProArt.*PA32UCXR",
        panel_type="Mini-LED",
        display_name="ProArt PA32UCXR",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6780, 0.3100),
            green=ChromaticityCoord(0.2650, 0.6900),
            blue=ChromaticityCoord(0.1380, 0.0520),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=1000.0,
            max_luminance_hdr=1600.0,
            min_luminance=0.005,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=False,
            local_dimming=True,
            local_dimming_zones=2304
        ),
        ddc=DDCRecommendations(
            picture_mode="User Mode 1",
            picture_mode_vcp=0x0B,
            color_preset="User",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use User Mode 1 or User Mode 2 for full DDC/CI RGB gain access. "
                  "Built-in motorized colorimeter for automatic scheduled self-calibration. "
                  "ProArt Calibration software stores hardware LUT profiles. "
                  "Also supports Calman and Light Illusion ColourSpace CMS. "
                  "Picture modes: Standard, sRGB, Adobe RGB, DCI-P3, Rec.2020, DICOM, "
                  "Rec.709, HDR_PQ DCI, HDR_PQ Rec.2020, HDR_HLG, Dolby Vision, User Mode 1/2. "
                  "2304 Mini-LED zones. VESA DisplayHDR 1400 certified. "
                  "Factory calibrated DeltaE <1. Thunderbolt 4 connectivity. "
                  "Local dimming may affect uniformity - disable for flat-field calibration."
        ),
        notes="Reference Mini-LED with built-in colorimeter. 97% DCI-P3, 99% Adobe RGB. "
              "2304 zones FALD. 1600 nits peak HDR. DeltaE <1 factory. Source: Tom's HW/ASUS."
    )

    # NEC MultiSync PA271Q (IPS 27" 1440p professional - NEC/Sharp)
    # Source: B&H Photo, DisplaySpecifications, NEC SpectraView
    panels["PA271Q"] = PanelCharacterization(
        manufacturer="NEC",
        model_pattern=r"PA271Q|MultiSync.*PA271Q|NEC.*PA271Q|Sharp.*PA271Q",
        panel_type="IPS",
        display_name="MultiSync PA271Q",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3320),
            green=ChromaticityCoord(0.2750, 0.6400),
            blue=ChromaticityCoord(0.1495, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=350.0,
            max_luminance_hdr=350.0,
            min_luminance=0.15,
            native_contrast=1500.0,
            bit_depth=10,
            hdr_capable=False,
            wide_gamut=True,
            vrr_capable=False,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom",
            picture_mode_vcp=0x0B,
            color_preset="Custom",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=60,
            initial_contrast=50,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="NEC SpectraView Engine provides hardware calibration via 14-bit LUT. "
                  "Use with SpectraView II or compatible calibration software. "
                  "98.5% Adobe RGB, 100% sRGB, 81.1% Rec.2020. "
                  "USB-C with 30W PD. DisplaySync Pro for multi-monitor color matching. "
                  "RJ-45 port for remote management. Memory port for USB sensor. "
                  "SpectraView Engine ensures color stability between calibrations. "
                  "Inputs: DP, Mini DP, HDMI (2x), USB-C. "
                  "4-year warranty with Advanced Exchange."
        ),
        notes="Professional 27-inch 1440p IPS. 98.5% Adobe RGB. SpectraView Engine hardware LUT. "
              "14-bit processing. USB-C 30W PD. Source: NEC/B&H."
    )

    # EIZO ColorEdge CG2700X (IPS 27" 4K reference with built-in sensor)
    # Source: EIZO product page
    panels["CG2700X"] = PanelCharacterization(
        manufacturer="EIZO",
        model_pattern=r"CG2700X|ColorEdge.*CG2700X|EIZO.*CG2700X",
        panel_type="IPS",
        display_name="ColorEdge CG2700X",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6780, 0.3100),
            green=ChromaticityCoord(0.2650, 0.6900),
            blue=ChromaticityCoord(0.1495, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=500.0,
            max_luminance_hdr=500.0,
            min_luminance=0.10,
            native_contrast=1450.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=False,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="User",
            picture_mode_vcp=0x0B,
            color_preset="User",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=50,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="TRUE REFERENCE MONITOR. Built-in swing-out calibration sensor. "
                  "ColorNavigator 7 software for hardware calibration via 16-bit LUT. "
                  "Color modes: User, BT.2020, BT.709, DCI-P3, PQ_DCI-P3, HLG_BT.2100, "
                  "AdobeRGB, sRGB, Calibration (CAL), SYNC_SIGNAL. "
                  "99% Adobe RGB, 98% DCI-P3. HDR gamma: HLG and PQ curves supported. "
                  "Digital Uniformity Equalizer (DUE) for screen uniformity. "
                  "AI-based temperature drift correction in real-time. "
                  "Sensor can be correlated with external spectroradiometers. "
                  "Nearest Neighbor interpolation option for pixel-accurate scaling. "
                  "Schedule automatic recalibration. Calibrate all color modes simultaneously."
        ),
        notes="True reference 27-inch 4K IPS. 99% Adobe RGB, 98% DCI-P3. Built-in sensor. "
              "16-bit LUT. ColorNavigator 7. DUE uniformity. Source: EIZO."
    )

    # BenQ SW272U (IPS 27" 4K photography monitor)
    # Source: BenQ specs, PCWorld review, Digital Camera World
    panels["SW272U"] = PanelCharacterization(
        manufacturer="BenQ",
        model_pattern=r"SW272U|BenQ.*SW272U|PhotoVue.*SW272U",
        panel_type="IPS",
        display_name="PhotoVue SW272U",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3320),
            green=ChromaticityCoord(0.2750, 0.6400),
            blue=ChromaticityCoord(0.1495, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=400.0,
            max_luminance_hdr=400.0,
            min_luminance=0.25,
            native_contrast=1000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=False,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Adobe RGB",
            picture_mode_vcp=0x0B,
            color_preset="User",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=50,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Photography-focused monitor with A.R.T. (Advanced Reflectionless Technology) panel. "
                  "Hardware calibration via Palette Master Ultimate and 16-bit 3D LUT. "
                  "Also supports Calman, Colorspace, and other 3rd-party calibration. "
                  "Color modes: sRGB, Rec.709, DCI-P3, Display P3, Adobe RGB, M-Book, Custom 1/2. "
                  "99% Adobe RGB, 99% DCI-P3, 100% sRGB. "
                  "Factory calibrated DeltaE <=1.5. Calman Verified. Pantone Validated. "
                  "Detachable shading hood bridge. VESA DisplayHDR 400. "
                  "3rd-gen Uniformity and Color Consistency technologies. "
                  "Paper-like matte finish reduces reflections. 60Hz only."
        ),
        notes="Photography 27-inch 4K IPS. 99% Adobe RGB, 99% DCI-P3. A.R.T. panel. "
              "16-bit 3D LUT hardware calibration. DeltaE <=1.5. Source: BenQ/PCWorld."
    )

    # Dell UltraSharp U3224KB (IPS Black 32" 6K Thunderbolt hub monitor)
    # Source: TFTCentral, Tom's Hardware, Dell specs
    panels["U3224KB"] = PanelCharacterization(
        manufacturer="Dell",
        model_pattern=r"U3224KB|Dell.*U3224KB|UltraSharp.*U3224KB",
        panel_type="IPS",
        display_name="UltraSharp U3224KB",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6780, 0.3100),
            green=ChromaticityCoord(0.2650, 0.6900),
            blue=ChromaticityCoord(0.1500, 0.0600),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=524.0,
            max_luminance_hdr=600.0,
            min_luminance=0.10,
            native_contrast=2000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=False,
            local_dimming=True,
            local_dimming_zones=0
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom Color",
            picture_mode_vcp=0x0B,
            color_preset="Custom Color",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=75,
            initial_contrast=75,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="Use Custom Color mode for DDC/CI RGB gain access. "
                  "IPS Black panel with 2000:1 contrast (measured ~1500:1). "
                  "6K resolution (6144x3456) - world's first 6K monitor. 224 PPI. "
                  "100% DCI-P3 coverage. VESA DisplayHDR 600 with edge-lit local dimming. "
                  "Thunderbolt 4, HDMI 2.1, DisplayPort 2.1 connectivity. "
                  "Built-in 4K HDR webcam with dual 14W speakers. "
                  "5x USB-C and 5x USB-A ports. Massive hub monitor. "
                  "No gaming features (60Hz, no VRR). Strictly productivity. "
                  "Dell Display Manager provides DDC/CI desktop control. "
                  "ComfortView must be off for accurate white balance."
        ),
        notes="6K IPS Black hub monitor. 100% DCI-P3. 2000:1 contrast ratio. "
              "Thunderbolt 4. 4K webcam. Source: Tom's Hardware/TFTCentral."
    )

    # ASUS ProArt PA32DC (RGB OLED 32" 4K professional with built-in colorimeter)
    # Source: PCMonitors.info review
    panels["PA32DC"] = PanelCharacterization(
        manufacturer="ASUS",
        model_pattern=r"PA32DC|ProArt.*PA32DC",
        panel_type="OLED",
        display_name="ProArt PA32DC",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6780, 0.3100),
            green=ChromaticityCoord(0.2650, 0.6900),
            blue=ChromaticityCoord(0.1380, 0.0520),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=264.0,
            max_luminance_hdr=545.0,
            min_luminance=0.0001,
            native_contrast=1000000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=False,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="User Mode 1",
            picture_mode_vcp=0x0B,
            color_preset="User",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=80,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="RGB OLED panel (not WOLED, not QD-OLED). Self-emissive per-pixel dimming. "
                  "Built-in motorized RGB colorimeter with ProArt Calibration software. "
                  "Supports 3D LUT hardware calibration. Also supports Calman and Light Illusion. "
                  "ProArt Presets: Standard, sRGB, Adobe RGB, DCI-P3, Rec.2020, DICOM, "
                  "Rec.709, User Mode 1/2, plus HDR variants. "
                  "Factory calibrated DeltaE <1. 99% DCI-P3, 99% Adobe RGB. "
                  "Schedule automatic colorimeter calibration (weekly/monthly). "
                  "Can be as dim as 6 cd/m2 - exceptional for dark room work. "
                  "HDR peak: 545 nits (small patch), 269 nits sustained full white."
        ),
        notes="Professional RGB OLED with built-in colorimeter. 99% DCI-P3, 99% Adobe RGB. "
              "3D LUT hardware calibration. DeltaE <1 factory. Source: PCMonitors.info."
    )

    # Philips 27E1N8900 (JOLED RGB OLED 27" 4K 60Hz professional)
    # Source: TFTCentral, PCMonitors, Philips specs
    panels["27E1N8900"] = PanelCharacterization(
        manufacturer="Philips",
        model_pattern=r"27E1N8900|Philips.*27E1N8900",
        panel_type="OLED",
        display_name="Momentum 27E1N8900",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6780, 0.3100),
            green=ChromaticityCoord(0.2650, 0.6900),
            blue=ChromaticityCoord(0.1380, 0.0520),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=250.0,
            max_luminance_hdr=540.0,
            min_luminance=0.0001,
            native_contrast=1000000.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=False,
            local_dimming=False
        ),
        ddc=DDCRecommendations(
            picture_mode="Custom",
            picture_mode_vcp=0x0B,
            color_preset="User Define",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=50,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="2.2",
            gamma_vcp_value=0x04,
            notes="JOLED RGB OLED panel (printed OLED technology). "
                  "NOT QD-OLED or WOLED - true RGB subpixel OLED. "
                  "Color presets: sRGB (DeltaE <1 specified), DCI-P3, Adobe RGB, User Define. "
                  "99.7% DCI-P3, 99.6% Adobe RGB, ~150% sRGB relative coverage. "
                  "Close-to-glossy screen surface with mild AG treatment. "
                  "VESA DisplayHDR True Black 400. Per-pixel dimming, no blooming. "
                  "USB-C with power delivery. 60Hz only. "
                  "Professional-grade OLED at moderate price point (~$1070 USD)."
        ),
        notes="JOLED RGB OLED 27-inch 4K. 99.7% DCI-P3, 99.6% Adobe RGB. "
              "True Black 400. 60Hz professional. Source: TFTCentral/Philips."
    )

    # AOC AGON Pro AG274QXM (IPS Mini-LED 27" 1440p 170Hz gaming)
    # Source: TFTCentral review
    panels["AG274QXM"] = PanelCharacterization(
        manufacturer="AOC",
        model_pattern=r"AG274QXM|AGON.*AG274QXM|AOC.*AG274QXM",
        panel_type="Mini-LED",
        display_name="AGON Pro AG274QXM",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6480, 0.3320),
            green=ChromaticityCoord(0.2750, 0.6400),
            blue=ChromaticityCoord(0.1495, 0.0580),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.1500, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.1500, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.1500, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=356.0,
            max_luminance_hdr=1000.0,
            min_luminance=0.05,
            native_contrast=992.0,
            bit_depth=10,
            hdr_capable=True,
            wide_gamut=True,
            vrr_capable=True,
            local_dimming=True,
            local_dimming_zones=576
        ),
        ddc=DDCRecommendations(
            picture_mode="User",
            picture_mode_vcp=0x0B,
            color_preset="User Define",
            color_preset_vcp=0x0B,
            disable_dynamic_contrast=True,
            disable_eco_mode=True,
            initial_brightness=50,
            initial_contrast=50,
            rgb_gain_range=(0, 100),
            rgb_offset_range=(0, 100),
            gamma_preset="Gamma3",
            gamma_vcp_value=0x04,
            notes="Use User picture mode for DDC/CI RGB gain access. "
                  "Innolux M270KCJ-Q7E IPS panel with Mini-LED backlight. "
                  "576 local dimming zones. VESA DisplayHDR 1000 certified. "
                  "NOTE: Brightness is locked in sRGB mode - use User mode. "
                  "98% DCI-P3, 97% Adobe RGB, 145% sRGB (oversaturated in native). "
                  "Measured gamma runs slightly low at 2.15 default. "
                  "FreeSync Premium Pro (48-170Hz with LFC). "
                  "Shadow Shield (detachable hood) included. "
                  "USB-C with DP Alt mode and 65W PD. Built-in KVM. "
                  "Blue light reduction modes affect color - disable for calibration. "
                  "1x DP, 2x HDMI 2.0 inputs."
        ),
        notes="Mini-LED gaming 27-inch 1440p. 576 zones. 98% DCI-P3. HDR 1000. "
              "Measured gamma ~2.15 default. Source: TFTCentral."
    )

    # Generic sRGB IPS (fallback for unknown panels)
    panels["GENERIC_SRGB"] = PanelCharacterization(
        manufacturer="Generic",
        model_pattern=r".*",  # Matches anything as fallback
        panel_type="IPS",
        display_name="Unknown Display",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6400, 0.3300),
            green=ChromaticityCoord(0.3000, 0.6000),
            blue=ChromaticityCoord(0.1500, 0.0600),
            white=ChromaticityCoord(0.3127, 0.3290)
        ),
        gamma_red=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=2.2000, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=250.0,
            max_luminance_hdr=400.0,
            min_luminance=0.1,
            native_contrast=1000.0,
            bit_depth=8,
            hdr_capable=False,
            wide_gamut=False,
            vrr_capable=False,
            local_dimming=False
        ),
        notes="Generic sRGB panel. Used as fallback when no specific profile exists."
    )

    return panels
