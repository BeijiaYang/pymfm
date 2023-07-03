from utils.forecast_generation import generate_forecast
from utils.scenario_generation import generate_scenario

# Example usage

forecast_input_folder = "inputs/forecast"
forecast_output_folder = "outputs/forecast"
time_resolution = 15  # in minutes

forecast_data = generate_forecast(
    forecast_input_folder, forecast_output_folder, time_resolution
)

forecast_input_file = "outputs/forecast/forecast_2021-04-01.json"
scenario_input_file = "inputs/scenario/scenario_src_2021-04-01.json"
scenario_output_file = "outputs/scenario/test.json"

generate_scenario(forecast_input_file, scenario_input_file, scenario_output_file)