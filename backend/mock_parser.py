def get_mock_drawing_data():
    """Returns the full 11-variable set for a standard Cargo Ship Cabin."""
    return {
        "transmission": 450.5,
        "solar": 280.0,
        "engine_radiant": 500.0,
        "thermal_lag": 1200.0,      # Variable 4 (Triggering Stress)
        "latent_heat": 650.0,       # Variable 5 (Triggering Mold)
        "metabolic": 230.0,
        "equipment": 450.0,
        "infiltration": 45.0,
        "ceiling_conduction": 120.0,
        "floor_conduction": 60.0,
        "total_raw_load": 4500.5    # Variable 11 (Total Load)
    }