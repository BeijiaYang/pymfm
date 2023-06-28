from utils.input_generation import generate_scenario, generate_optimizer_input

# Example usage
input_folder = "inputs"
output_folder = "outputs"
time_resolution = 15  # in minutes
uc_name = "optimiser"
day_end = "2021-04-01T11:00:00.000Z"
bulk = {
    "with_bulk": False,
    "bulk_start": "2021-04-01T13:00:00.000Z",
    "bulk_end": "2021-04-01T17:00:00.000Z",
    "bulk_energy_kWh": 100,
}
import_export_limitation = {
    "with_import_limit": True,
    "with_export_limit": False,
    "import_limit": 1000000,
    "export_limit": 100000,
}
battery_specs = [
    {
        "id": "bat_1",
        "bat_type": "cbes",
        "with_final_SoC": True,
        "initial_SoC": 60,
        "final_SoC": 87,
        "P_dis_max_kW": 300,
        "P_ch_max_kW": 300,
        "min_SoC": 8.75,
        "max_SoC": 87.5,
        "bat_capacity": 800,
        "ch_efficiency": 1,
        "dis_efficiency": 1,
    },
    {
        "id": "bat_2",
        "bat_type": "hbes",
        "with_final_SoC": True,
        "initial_SoC": 40,
        "final_SoC": 61.4,
        "P_dis_max_kW": 30,
        "P_ch_max_kW": 30,
        "min_SoC": 8.75,
        "max_SoC": 87.5,
        "bat_capacity": 80,
        "ch_efficiency": 1,
        "dis_efficiency": 1,
    },
]

scenario_data = generate_scenario(input_folder, time_resolution)

generate_optimizer_input(
    scenario_data,
    uc_name,
    day_end,
    bulk,
    import_export_limitation,
    battery_specs,
    output_folder,
)
