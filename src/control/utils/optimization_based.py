import pandas as pd
from pyomo.environ import SolverFactory
from pyomo.core import *
from utils.data_input import Bulk
from pyomo.opt import SolverStatus
import pyomo.kernel as pmo


# Constraints


def power_balance(model, t):
    return (
        model.P_load_kW[t]
        + sum(model.P_ch_bat_kW[n, t] for n in model.N)
        + model.P_exp_kW[t] * model.x_exp[t]
        == sum(model.P_dis_bat_kW[n, t] for n in model.N)
        + model.P_imp_kW[t] * model.x_imp[t]
        + model.P_PV_kW[t]
    )


def bat_charging(model, n, t):
    return model.SoC_bat[n, t + model.dT] == model.SoC_bat[n, t] + model.dT.seconds * (
        (model.P_ch_bat_kW[n, t] / model.ch_eff_bat[n]) / model.bat_capacity_kWs[n]
    ) - model.dT.seconds * (
        (model.P_dis_bat_kW[n, t] * model.dis_eff_bat[n]) / model.bat_capacity_kWs[n]
    )


def bat_init_SoC(model, n):
    return model.SoC_bat[n, model.start_time] == model.ini_SoC_bat[n]


def bat_max_ch_power(model, n, t):
    return model.P_ch_bat_kW[n, t] <= float(model.P_ch_bat_max_kW[n]) * model.x_ch[n, t]


def bat_max_dis_power(model, n, t):
    return (
        model.P_dis_bat_kW[n, t] <= float(model.P_dis_bat_max_kW[n]) * model.x_dis[n, t]
    )


def bat_min_SoC(model, n, t):
    return float(model.min_SoC_bat[n]) <= model.SoC_bat[n, t]


def bat_max_SoC(model, n, t):
    return model.SoC_bat[n, t] <= model.max_SoC_bat[n]


def import_export_lower_bound(model, t):
    if model.with_lower_bound[t]:
        return (
            model.lower_bound_kW[t]
            <= model.P_imp_kW[t] * model.x_imp[t] - model.P_exp_kW[t] * model.x_exp[t]
        )
    else:
        return Constraint.Feasible


def import_export_upper_bound(model, t):
    if model.with_upper_bound[t]:
        return (
            model.P_imp_kW[t] * model.x_imp[t] - model.P_exp_kW[t] * model.x_exp[t]
            <= model.upper_bound_kW[t]
        )
    else:
        return Constraint.Feasible


def bat_final_SoC(model, n):
    if model.final_SoC_bat[n] is not None:
        # Household battery should reach its maximum SoC at the end of the day
        if model.bat_type[n] == "hbes":
            return model.SoC_bat[n, model.day_end] == model.max_SoC_bat[n]
        else:
            return model.SoC_bat[n, model.end_time] == model.final_SoC_bat[n]
    else:
        return Constraint.Feasible


def bulk_energy(model):
    return (
        sum(
            sum(
                (
                    model.P_dis_bat_kW[n, t] * model.dis_eff_bat[n]
                    - (model.P_ch_bat_kW[n, t]) / model.ch_eff_bat[n]
                )
                * model.dT.seconds
                for t in model.T_bulk
            )
            for n in model.N
        )
        == -model.bulk_energy_kWs[0]
    )


def ch_dis_binary(model, n, t):
    return model.x_ch[n, t] + model.x_dis[n, t] <= 1


def imp_exp_binary(model, t):
    return model.x_imp[t] + model.x_exp[t] <= 1


def deficit_case_1(model, t):
    if model.P_net_before_kW[t] >= 0:
        return model.P_imp_kW[t] * model.x_imp[t] <= model.P_net_before_kW[t]
    else:
        return Constraint.Feasible


def deficit_case_2(model, n, t):
    if model.P_net_before_kW[t] >= 0:
        return model.P_ch_bat_kW[n, t] <= 0
    else:
        return Constraint.Feasible


def surplus_case_1(model, t):
    if model.P_net_before_kW[t] <= 0:
        return (
            sum((model.P_ch_bat_kW[n, t]) / model.ch_eff_bat[n] for n in model.N)
            <= -model.P_net_before_kW[t]
        )
    else:
        return Constraint.Feasible


def surplus_case_2(model, t):
    if model.P_net_before_kW[t] <= 0:
        # Note for the future works: As we seperated P_imp_kW and x_imp from each other, make sure we always use P_imp_kW in all of our constraints.
        # From now on x_imp can be 1 and P_imp_kW can be 0, therefore we MUST use P_imp_kW in the constraints.
        return model.P_imp_kW[t] * model.x_imp[t] <= 0
    else:
        return Constraint.Feasible


def penalty_for_imp(model, t):
    return model.P_imp_kW[t] * model.x_imp[t] <= model.alpha_imp


def penalty_for_exp(model, t):
    return model.P_exp_kW[t] * model.x_exp[t] <= model.alpha_exp


def hbes_avoid_diss(model, n, t):
    if model.bat_type[n] == "hbes":
        return model.P_dis_bat_kW[n, t] <= 0
    else:
        return Constraint.Feasible


def pv_curtailment_constr(model, t):
    if model.pv_curtailment:
        return model.P_PV_kW[t] <= model.P_PV_limit_kW[t]
    else:
        return model.P_PV_kW[t] == model.P_PV_limit_kW[t]


# Objective: Minimize the power exchange with the grid (Minimum interaction with the grid)
def obj_rule(model):
    return (
        sum(
            model.P_exp_kW[t] * model.x_exp[t] + model.P_imp_kW[t] * model.x_imp[t]
            for t in model.T
        )
        + model.alpha_exp
        + model.alpha_imp
    )


def scheduling(
    P_load_gen: pd.Series,
    df_battery: pd.DataFrame,
    day_end,
    bulk_data: Bulk,
    imp_exp_limits: pd.DataFrame,
    pv_curtailment: Boolean,
) -> tuple[pd.Series, pd.Series, pd.DataFrame, pd.DataFrame, SolverStatus]:
    # Selected optimization solver
    # optimization_solver = SolverFactory("bonmin")
    optimization_solver = SolverFactory("gurobi")
    # optimization_solver = SolverFactory("ipopt")
    # optimization_solver = SolverFactory("scip")
    load = P_load_gen.P_load_kW
    generation = P_load_gen.P_gen_kW
    start_time = load.index[0]
    end_time = load.index[-1]
    delta_T = pd.to_timedelta(load.index.freq)
    # XXX it is a bit weird to that the end time is not the time of the end
    # but the start of the last interval
    opt_horizon = pd.date_range(
        start_time, end_time + delta_T, freq=delta_T, inclusive="left"
    )
    sof_horizon = pd.date_range(
        start_time, end_time + delta_T, freq=delta_T, inclusive="both"
    )
    if bulk_data is not None:
        bulk_horizon = pd.date_range(
            bulk_data.bulk_start, bulk_data.bulk_end, freq=delta_T, inclusive="both"
        )

    considered_load_forecast = load[
        opt_horizon
    ]  # Only the specified time instances in the load forecast will be taken into account
    considered_generation_forecast = generation[
        opt_horizon
    ]  # Only the specified time instances in the generation forecast will be taken into account

    #####################################################################################################
    ##################################       OPTIMIZATION MODEL          #################################
    model = ConcreteModel()

    # Index sets
    # Index set with aggregated battery identifiers
    model.N = list(df_battery.index)
    # Index set with optimization horizon time step identifiers
    # XXX Not sure why generating a tuple here makes a difference but it does
    model.T = tuple(opt_horizon)
    # Index set with battery horizon time step identifiers
    model.T_SoC_bat = tuple(sof_horizon)
    # Index set with bulk horizon time step identifiers
    if bulk_data is not None:
        model.T_bulk = tuple(bulk_horizon)

    # Parameters
    # TimeDelta in one time step
    model.dT = delta_T
    model.start_time = start_time
    model.end_time = end_time
    model.day_end = day_end
    # Import-export limits for every each timestamp enabling the microgrid to go full islanding (if both are zero)
    model.upper_bound_kW = imp_exp_limits.upper_bound
    model.lower_bound_kW = imp_exp_limits.lower_bound
    model.with_upper_bound = imp_exp_limits.with_upper_bound
    model.with_lower_bound = imp_exp_limits.with_lower_bound

    # Forecast parameters
    # Total load and generation forecast
    model.P_net_before_kW = considered_load_forecast - considered_generation_forecast
    # Load
    model.P_load_kW = considered_load_forecast
    # Generation limits
    model.P_PV_limit_kW = considered_generation_forecast
    # Battery parameters
    # Type of the battery
    # cbes: comunity battery energy storage, hbes: household battery energy storage
    model.bat_type = df_battery.bat_type
    # Minimum allowable state of charge of the battery n
    model.min_SoC_bat = df_battery.min_SoC
    # Maximum allowable state of charge of the battery n
    model.max_SoC_bat = df_battery.max_SoC
    # State of charge value of battery n at the beginning of the optimization horizon
    model.ini_SoC_bat = df_battery.initial_SoC
    # The value of the final state of charge (if given) to be reached for the battery n at the end of the optimization horizon
    model.final_SoC_bat = df_battery.final_SoC
    # Capacity of the battery n (kWsec)
    model.bat_capacity_kWs = df_battery.bat_capacity_kWs
    # Maximum charging power of the battery n (KW)
    model.P_ch_bat_max_kW = df_battery.P_ch_max_kW
    # Maximum discharging power of the battery n (KW)
    model.P_dis_bat_max_kW = df_battery.P_dis_max_kW
    # Charging efficiency of the battery n
    model.ch_eff_bat = df_battery.ch_efficiency
    # Discharging efficiency of the battery n
    model.dis_eff_bat = df_battery.dis_efficiency
    # Bulk parameters (bulk energy)
    if bulk_data is not None:
        # Bulk energy of battery assets (kWsec)
        model.bulk_energy_kWs = pd.Series([bulk_data.bulk_energy_kWh]) * 3600
    if pv_curtailment is not None:
        model.pv_curtailment = pv_curtailment
    else:
        model.pv_curtailment = False

    # Variables
    # Power output of PV in timestamp t
    model.P_PV_kW = Var(model.T, within=NonNegativeReals)
    # Power demand of the community in timestamp t
    model.P_dem_kW = Var(model.T, within=NonNegativeReals)
    # PV power feeding the load in timestamp t
    model.P_PV_dem_kW = Var(model.T, within=NonNegativeReals)
    # State of charge of the battery n in timestamp t
    model.SoC_bat = Var(model.N, model.T_SoC_bat, within=NonNegativeReals)
    # Charge power of the battery n in timestamp t
    model.P_ch_bat_kW = Var(model.N, model.T, within=NonNegativeReals)
    # Discharge power of the battery n in timestamp t
    model.P_dis_bat_kW = Var(model.N, model.T, within=NonNegativeReals)
    # Export power to the grid in timestamp t
    model.P_exp_kW = Var(model.T, within=NonNegativeReals)
    # Import power from the grid in timestamp t
    model.P_imp_kW = Var(model.T, within=NonNegativeReals)
    # Penalty variable for import (maximum value of P_imp_kW over time)
    model.alpha_imp = Var(within=NonNegativeReals)
    # Penalty variable for export (maximum value of P_exp_kW over time)
    model.alpha_exp = Var(within=NonNegativeReals)

    # Binary variables
    # Binary variable having 1 if battery n is charged at timestamp t
    model.x_ch = Var(model.N, model.T, within=pmo.Binary)
    # Binary variable having 1 if battery n is discharged at timestamp t
    model.x_dis = Var(model.N, model.T, within=pmo.Binary)
    # Binary variable having 1 if battery n imports power at timestamp t
    model.x_imp = Var(model.T, within=pmo.Binary)
    # Binary variable having 1 if battery n exports power at timestamp t
    model.x_exp = Var(model.T, within=pmo.Binary)

    model.power_balance = Constraint(model.T, rule=power_balance)
    model.bat_charging = Constraint(model.N, model.T, rule=bat_charging)
    model.bat_init_SoC = Constraint(model.N, rule=bat_init_SoC)
    model.bat_final_SoC = Constraint(model.N, rule=bat_final_SoC)
    if bulk_data is not None:
        model.bulk_energy = Constraint(rule=bulk_energy)
    model.bat_max_ch_power = Constraint(model.N, model.T, rule=bat_max_ch_power)
    model.bat_max_dis_power = Constraint(model.N, model.T, rule=bat_max_dis_power)
    model.bat_min_SoC = Constraint(model.N, model.T_SoC_bat, rule=bat_min_SoC)
    model.bat_max_SoC = Constraint(model.N, model.T_SoC_bat, rule=bat_max_SoC)
    model.import_export_upper_bound = Constraint(
        model.T, rule=import_export_upper_bound
    )
    model.import_export_lower_bound = Constraint(
        model.T, rule=import_export_lower_bound
    )
    model.ch_dis_binary = Constraint(model.N, model.T, rule=ch_dis_binary)
    model.imp_exp_binary = Constraint(model.T, rule=imp_exp_binary)
    model.penalty_for_imp = Constraint(model.T, rule=penalty_for_imp)
    model.penalty_for_exp = Constraint(model.T, rule=penalty_for_exp)
    model.deficit_case_1 = Constraint(model.T, rule=deficit_case_1)
    model.deficit_case_2 = Constraint(model.N, model.T, rule=deficit_case_2)
    model.surplus_case_1 = Constraint(model.T, rule=surplus_case_1)
    model.surplus_case_2 = Constraint(model.T, rule=surplus_case_2)
    model.hbes_avoid_diss = Constraint(model.N, model.T, rule=hbes_avoid_diss)
    model.pv_curtailment_constr = Constraint(model.T, rule=pv_curtailment_constr)

    model.obj = Objective(rule=obj_rule, sense=minimize)

    #####################################################################################################
    ##################################       OPTIMIZATION MODEL          ################################
    solver = optimization_solver.solve(model).solver
    #####################################################################################################
    ##################################       POST PROCESSING             ################################
    bat_P_supply_profiles = pd.DataFrame(index=model.T, columns=df_battery.index)
    P_net_after_kW = pd.DataFrame(index=model.T, columns=[""])
    bat_ch = pd.DataFrame(index=model.T, columns=df_battery.index)
    bat_dis = pd.DataFrame(index=model.T, columns=df_battery.index)
    bat_SoC_supply_profiles = pd.DataFrame(
        index=model.T_SoC_bat, columns=df_battery.index
    )

    for n in model.N:
        for t in model.T:
            bat_P_supply_profiles.loc[t, n] = value(
                model.x_dis[n, t] * model.P_dis_bat_kW[n, t] / model.dis_eff_bat[n]
                - model.x_ch[n, t] * model.P_ch_bat_kW[n, t] * model.ch_eff_bat[n]
            )

    for t in model.T:
        P_net_after_kW.loc[t] = value(
            model.x_imp[t] * model.P_imp_kW[t] - model.x_exp[t] * model.P_exp_kW[t]
        )

    for col in df_battery.index:
        bat_ch[col] = model.P_ch_bat_kW[col, :]()
        bat_dis[col] = model.P_dis_bat_kW[col, :]()
        bat_SoC_supply_profiles[col] = model.SoC_bat[col, :]()

    PV_profile = pd.Series(model.P_PV_kW[:](), index=model.T)

    return (
        P_net_after_kW,
        PV_profile,
        bat_P_supply_profiles,
        bat_SoC_supply_profiles,
        model.upper_bound_kW,
        model.lower_bound_kW,
        (solver.status, solver.termination_condition),
    )

def prep_output_df(
    P_net_after_kW: pd.Series,
    pv_profile: pd.Series,
    bat_p_supply_profiles: pd.DataFrame,
    bat_soc_supply_profiles: pd.DataFrame,
    df_forecasts: pd.DataFrame,
    imp_exp_upperb,
    imp_exp_lowerb,
):
    output_df = pd.DataFrame(index=df_forecasts.index)
    output_df["P_net_before_kW"] = (
        df_forecasts["P_load_kW"] - df_forecasts["P_gen_kW"]
    )
    output_df["P_net_before_controlled_PV_kW"] = (
        df_forecasts["P_load_kW"] - pv_profile
    )
    output_df["P_PV_forecast_kW"] = df_forecasts["P_gen_kW"]
    output_df["P_PV_controlled_kW"] = pv_profile
    output_df["P_net_after_kW"] = P_net_after_kW
    output_df["upperb"] = imp_exp_upperb
    output_df["lowerb"] = imp_exp_lowerb
    for col in bat_p_supply_profiles.columns:
        output_df[f"P_{col}_kW"] = bat_p_supply_profiles[col]
        output_df[f"SoC_{col}_%"] = bat_soc_supply_profiles[col] * 100

    return output_df