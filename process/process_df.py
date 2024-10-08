from Connect.connect import create_db_url
from .process_records import create_reference_ids_set, create_reference_ids_set_distinct, create_reference_names_set
import numpy as np
import pandas as pd
import asyncio
import asyncpg


# na_values = ['', '#N/A', '#N/A N/A', '#NA', '-1.#IND',
#             '-1.#QNAN', '-NaN', '-nan', '1.#IND',
#             '1.#QNAN', 'N/A', 'NULL', 'NaN',
#             'n/a', 'null']

def combine_dfs(combined_dfs, dfs):
    for file_name, dfs_dict in dfs.items():
        for category, df_list in dfs_dict.items():
            if df_list:
                dfs_with_year = []
                for df in df_list:
                    dfs_with_year.append((df["year"].iloc[0], df))
                sorted_dfs_with_year = sorted(dfs_with_year, key=lambda x: x[0])
                sorted_dfs = [df for year, df in sorted_dfs_with_year]
                merged_df = pd.concat(sorted_dfs, ignore_index=True)

                combined_dfs[file_name][category] = create_index_column(merged_df)


def create_index_column(df):
    df.reset_index(inplace=True)
    return df

def standardized_duration(df):
    mask = df["Duration"].str.count(":") == 2
    df.loc[mask, "Duration"] = "0" + df.loc[mask, "Duration"]

    mask = df["Duration"].str.count(":") == 1
    df.loc[mask, "Duration"] = "00:" + df.loc[mask, "Duration"]

    df["Duration"].fillna("00:00:00", inplace=True)

    hours = df['Duration'].str.split(':').str[0].astype("int32")
    minutes = df['Duration'].str.split(':').str[1].astype("int32")
    seconds = df['Duration'].str.split(':').str[2].astype("int32")

    df['Duration'] = hours * 3600 + minutes * 60 + seconds

    return df

def convert_to_ints(df):
    int_with_na_columns = ["initiated", "player_kills", "enemy_kills", "difference", "two_kills", "three_kills", "four_kills", "five_kills", "one_vs_one", "one_vs_two", "one_vs_three",
               "one_vs_four", "one_vs_five", "econ", "spike_plants", "spike_defuses", "year", "team_a_defender_score", "team_b_defender_score", "team_a_overtime_score",
                "team_b_overtime_score", "duration", "acs", "kd", "fk", "fd", "fkd"]
    for column in int_with_na_columns:
        if column == "kd" and "teams" in df:
            continue
        elif column in df:
            df[column] = df[column].astype("Int64")
    return df

def convert_clutches(df):
    df["Clutches (won/played)"] = df["Clutches (won/played)"].fillna("0/0")
    clutches_split = df['Clutches (won/played)'].str.split('/', expand=True)
    df["Clutches Won"] = clutches_split[0]
    df["Clutches Played"] = clutches_split[1]
    mask = (df["Clutches (won/played)"] == '0/0')
    df.loc[mask, ["Clutches Won", "Clutches Played"]] = pd.NA
    return df

def convert_percentages_to_decimal(df):
    columns = [ "Kill, Assist, Trade, Survive %", "Headshot %", "Pick Rate", "Attacker Side Win Percentage", "Defender Side Win Percentage",
               "Clutch Success %"]
    for column in columns:
        if column in df:
            mask = df[column].str.contains("%", na=False)
            df.loc[mask, column] = df.loc[mask, column].str.rstrip("%").astype("float32") / 100
    return df


def convert_missing_numbers(df):
    for column in ["Rating", "Average Combat Score", "Kills", "Deaths", "Assists", "Kills - Deaths (KD)", "Average Damage per Round",
                   "First Kills", "First Deaths", "Kills - Deaths (FKD)", "Team A Overtime Score",
                   "Team B Overtime Score", "2k", "3k", "4k", "5k", "1v1", "1v2", "1v3", "1v4", "1v5", "Player Kills", "Enemy Kills", "Difference",
                   "Initiated"]:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce", downcast="float")
    return df

def add_missing_ids(df, column, missing_numbers, null_count):
    df.loc[df[column].isnull(), column] = missing_numbers[:null_count]
    if column == "Player ID":
        df.loc[len(df.index)] = [pd.NA, 0]


def add_player_nan(df):
    condition = (
        (df['Tournament'] == "Champions Tour Philippines Stage 1: Challengers 2") &
        (df['Stage'].isin(["Qualifier 1", "All Stages"])) &
        (df['Match Type'].isin(["Round of 16", "All Match Types"])) &
        (df['Player'].isnull()) &
        (df['Agents'] == "reyna")
    )
    if "Match Name" in df:
        player_nan_overview_condition = (df['Tournament'] == 'Champions Tour Philippines Stage 1: Challengers 2') & \
                                        (df['Stage'] == 'Qualifier 1') & \
                                        (df['Match Type'] == 'Round of 16') & \
                                        (df['Player'].isnull()) & \
                                        (df["Match Name"] == "KADILIMAN vs MGS Spades")
        filtered_indices = df.index[player_nan_overview_condition]
        df.loc[filtered_indices, "Player"] = "nan"
    filtered_indices = df.index[condition]
    df.loc[filtered_indices, "Player"] = "nan"
    return df

def get_missing_numbers(df, column):
   min_id = int(df[column].min())
   max_id = int(df[column].max())
   all_numbers = set(range(min_id, max_id + 1))
   null_count = df[column].isnull().sum()
   missing_numbers = sorted(all_numbers - set(df[column]))
   np.random.shuffle(missing_numbers)
   return null_count, missing_numbers

def k_to_numeric(df, column):
    df[column] = df[column].str.replace("k", "")
    df[column] = df[column].astype("float32")
    df[column] *= 1000
    df[column] = df[column].astype("float32")
    return df

def get_eco_type(df):
    df["Type"] = df["Type"].str.split(":").str[0]
    return df

def get_upper_round_id(df):
    upper_round_df = df[(df["Tournament ID"] == 560) &
                       (df["Stage ID"] == 1096) &
                       (df["Match Type"] == "Upper Round 1")]
    upper_round_id = upper_round_df["Match Type ID"].values[0]
    return upper_round_id

def convert_reference_columns_to_category(df):
    columns = ["Tournament", "Stage", "Match Type", "Match Name", "Agents", "Eliminator", "Eliminated", "Eliminator Team", "Eliminated Team",
               "Eliminator Agent", "Eliminated Agent", "Team A", "Team B", "Player Team", "Enemy Team", "Team", "Player", "Player Team",
               "Map", "Agent"]
    for column in columns:
        if column in df:
            df[column] = df[column].astype("category")
    return df

def drop_columns(df):
    columns = ["Tournament", "Stage", "Match Type", "Match Name", "Team", "Map", "Player", "Player Team", "Enemy Team", "Enemy",
               "Team A", "Team B", "Eliminator", "Eliminator Team", "Eliminated", "Eliminated Team", "Agent", "Clutches (won/played)"]
    for column in columns:
        if column in df and "Time Expiry (Failed to Plant)" not in df:
            df.drop(columns=column, inplace=True)
    return df

def reorder_columns(df, column_names):
    return df.reindex(columns=column_names)

def rename_columns(df):
    stats_columns = {"Average Combat Score": "acs", "Kills - Deaths (KD)": "kd", "Kill, Assist, Trade, Survive %": "kast",
                     "Average Damage Per Round": "adpr", "Headshot %": "headshot", "First Kills": "fk", "First Deaths": "fd",
                     "Kills - Deaths (FKD)": "fkd", "Kills:Deaths": "kd", "Kills Per Round": "kpr", "Assists Per Round": "apr",
                     "First Kills Per Round": "fkpr", "First Deaths Per Round": "fdpr", "Clutch Success %": "clutch_success",
                     "Maximum Kills in a Single Map": "mksp", "2k": "two_kills", "3k": "three_kills", "4k": "four_kills", "5k": "five_kills",
                     "1v1": "one_vs_one", "1v2": "one_vs_two", "1v3": "one_vs_three", "1v4": "one_vs_four", "1v5": "one_vs_five"}
    for column in df.columns:
        if column in stats_columns:
            new_column_name = stats_columns[column]
        else:    
            new_column_name = column.lower().replace(" ", "_").replace("(", "").replace(")", "")
        df.rename(columns={column: new_column_name}, inplace=True)
    return df

def remove_nan_rows(df, cols):
    df = df.dropna(subset=cols, how='all')
    return df

def csv_to_df(file):
    return pd.read_csv(file)


def splitting_teams(df):
    df['teams'] = df['teams'].replace('Stay Small, Stay Second', 'Stay Small; Stay Second', regex=True)
    df.loc[:, "teams"] = df["teams"].str.split(", ")
    df = df.explode("teams")
    df['teams'] = df['teams'].replace('Stay Small; Stay Second', 'Stay Small, Stay Second', regex=True)

    return df

def splitting_agents(df):
    df.loc[:, "agents"] = df["agents"].str.split(", ")
    df = df.explode("agents")
    return df

def add_missing_player(df, year):
    if "Player" in df and "Player ID" in df:
        if year == 2021:
            nan_player = df[df["Player ID"] == 10207].index
            df.loc[nan_player, "Player"] = "nan"
            df.loc[len(df.index)] = ["pATE", 9505]
            df.loc[len(df.index)] = ["Wendigo", 26880]
        elif year == 2022:
            df.loc[len(df.index)] = ["Wendigo", 26880]
        df.drop_duplicates(inplace=True, subset=["Player", "Player ID"])
        df.reset_index(drop=True, inplace=True)
    return df

def remove_leading_zeroes_from_players(df):
    columns = ["Player", "Eliminated", "Eliminator", "Enemy"]
    for column in columns:
        if column in df and "Time Expiry (Failed to Plant)" not in df:
            mask = df[df[column] == "002"].index
            df.loc[mask, column] = "2"
            mask = df[df[column] == "01000010"].index
            df.loc[mask, column] = "1000010"
    return df

def create_boolean_indexing(df, ids, columns):
    conditions = []
    values = []
    for key, value in ids.items():
        if len(columns) > 1:
            compound_condition = [df[columns[i]] == key[i] for i in range(len(key))]
            conditions.append(np.logical_and.reduce(compound_condition))
        else:
            conditions.append(df[columns[0]] == key)
        values.append(value)
    return conditions, values

async def new_data(df, table, year, pool):
    df_tournaments = list(df["Tournament"].unique())
    df_tournament_ids = await create_reference_ids_set(pool, "tournaments", "tournament_id", "tournament", df_tournaments, year)
    distinct_tournament_ids = await create_reference_ids_set_distinct(pool, table, "tournament_id", year)
    new_tournament_ids = list(df_tournament_ids ^ distinct_tournament_ids)
    if new_tournament_ids:
        new_tournaments = await create_reference_names_set(pool, "tournaments", "tournament_id", "tournament", new_tournament_ids)
        new_tournaments = list(new_tournaments)
        filtered_df = df[df["Tournament"].isin(new_tournaments)]
        return filtered_df
    else:
        return pd.DataFrame()


async def process_column(df, df_column, table_name, reference_ids):
    names_set = set(df[df_column])
    dict_keys_set = set(reference_ids[table_name].keys())
    intersection_names = names_set & dict_keys_set
    ids = {name: reference_ids[table_name][name] for name in intersection_names}
    conditions, result_values = create_boolean_indexing(df, ids, [df_column])
    df[f"{df_column} ID"] = np.select(conditions, result_values)
    if table_name == "players":
        df[f"{df_column} ID"] = df[f"{df_column} ID"].astype("UInt32")
    else:
        df[f"{df_column} ID"] = df[f"{df_column} ID"].astype("UInt16")

async def process_tournaments_stages_match_types_matches(df, year, reference_ids):
    if "Tournament" in df:
        tournament_ids = reference_ids["tournaments"][year]
        columns = ["Tournament"]
        conditions, values = create_boolean_indexing(df, tournament_ids, columns)
        df["Tournament ID"] = np.select(conditions, values)
        if "Stage" in df:
            stage_ids = reference_ids["stages"][year]
            columns = ["Stage", "Tournament ID"]
            conditions, values = create_boolean_indexing(df, stage_ids, columns)
            df["Stage ID"] = np.select(conditions, values)
            if "Match Type" in df:
                columns = ["Match Type", "Tournament ID", "Stage ID"]
                match_types_ids = reference_ids["match_types"][year]
                conditions, values = create_boolean_indexing(df, match_types_ids, columns)
                df["Match Type ID"] = np.select(conditions, values)
                if "Match Name" in df:
                    columns = ["Match Name", "Tournament ID", "Stage ID", "Match Type ID"]
                    matches_ids = reference_ids["matches"][year]
                    conditions, values = create_boolean_indexing(df, matches_ids, columns)
                    df["Match ID"] = np.select(conditions, values)

async def process_teams(df, reference_ids):
    team_columns = ["Team", "Player Team", "Enemy Team", "Eliminator Team", "Eliminated Team", "Team A", "Team B"]
    await asyncio.gather(
        *(process_column(df, column, "teams", reference_ids) for column in team_columns if column in df)
    )

async def process_players(df, reference_ids):
    player_columns = ["Player", "Enemy", "Eliminator", "Eliminated"]
    await asyncio.gather(
        *(process_column(df, column, "players", reference_ids) for column in player_columns if column in df and "Time Expiry (Failed to Plant)" not in df)
        )

async def process_agents(df, reference_ids):
    agent_columns = ["Eliminator Agent", "Eliminated Agent", "Agent"]
    await asyncio.gather(
        *(process_column(df, column, "agents", reference_ids) for column in agent_columns if column in df)
    )

async def process_maps(df, reference_ids):
    if "Map" in df:
        await process_column(df, "Map", "maps", reference_ids)

async def change_reference_name_to_id(df, year, reference_ids):
    tasks = [
        asyncio.create_task(process_tournaments_stages_match_types_matches(df, year, reference_ids)),
        asyncio.create_task(process_players(df, reference_ids)),
        asyncio.create_task(process_teams(df, reference_ids)),
        asyncio.create_task(process_maps(df, reference_ids)),
        asyncio.create_task(process_agents(df, reference_ids))
    ]
    await asyncio.gather(*tasks)

    return df

def process_tournaments_stages_match_types(df):
    df = df[["Tournament", "Tournament ID", "Stage", "Stage ID", "Match Type", "Match Type ID", "Year"]]
    df = df.drop_duplicates()
    null_stage_count, missing_stage_ids = get_missing_numbers(df, "Stage ID")
    null_match_type_count, missing_match_type_ids = get_missing_numbers(df, "Match Type ID")
    add_missing_ids(df, "Stage ID", missing_stage_ids, null_stage_count)
    add_missing_ids(df, "Match Type ID", missing_match_type_ids, null_match_type_count)
    return df

def process_tournaments(df):
   df = df[["Tournament", "Tournament ID", "Year"]]
   df = df.drop_duplicates()
   df = rename_columns(df)
   df = reorder_columns(df, ["tournament_id", "tournament", "year"])
   return df

def process_stages(df):
   df = df[["Tournament ID", "Stage", "Stage ID", "Year"]]
   df = df.drop_duplicates()
   df = rename_columns(df) 
   df = reorder_columns(df, ["stage_id", "tournament_id", "stage", "year"])
   return df

def process_match_types(df):
   df = df[["Tournament ID", "Stage ID", "Match Type", "Match Type ID", "Year"]]
   df = df.drop_duplicates()
   df = rename_columns(df)
   df = reorder_columns(df, ["match_type_id", "tournament_id", "stage_id", "match_type", "year"])
   return df

def process_matches(df, upper_round_id):
    filtered = df[(df["Tournament ID"] == 560) &
                  (df["Stage ID"] == 1096) &
                  (df["Match Type"] == "Upper Round 1")]
    df = df[["Tournament ID", "Stage ID", "Match Type ID", "Match Name", "Match ID", "Year"]]
    df.loc[filtered.index, "Match Type ID"] = upper_round_id
    df = df.drop_duplicates()
    df.rename(columns={"Match Name": "Match"}, inplace=True)
    df = rename_columns(df)
    df = reorder_columns(df, ["match_id", "tournament_id", "stage_id", "match_type_id", "match", "year"])
    return df

def process_teams_ids(df):
   df = df[["Team", "Team ID"]]
   df = df.drop_duplicates()
   null_team_count, missing_team_id = get_missing_numbers(df, "Team ID")
   add_missing_ids(df, "Team ID", missing_team_id, null_team_count)
   df = rename_columns(df)
   df = reorder_columns(df, {"team_id", "team"})
   return df

def process_players_ids(df):
   df = df[["Player", "Player ID"]]
   df = df.drop_duplicates()
   null_player_count, missing_player_id = get_missing_numbers(df, "Player ID")
   add_missing_ids(df, "Player ID", missing_player_id, null_player_count)
   df = add_missing_player(df, 2021)
   df = remove_leading_zeroes_from_players(df)
   df = rename_columns(df)
   df = reorder_columns(df, {"player_id", "player"})
   return df

async def process_drafts(file, file_name, table_name, year, dfs, reference_ids, pool):
    drafts_df = csv_to_df(file)
    drafts_df = await new_data(drafts_df, table_name, year, pool)
    if len(drafts_df.index) > 0:
        drafts_df = convert_reference_columns_to_category(drafts_df)
        drafts_df = await change_reference_name_to_id(drafts_df, year, reference_ids)
        drafts_df = drop_columns(drafts_df)
        drafts_df = rename_columns(drafts_df)
        drafts_df = reorder_columns(drafts_df, ["tournament_id", "stage_id", "match_type_id", "match_id", "team_id", "map_id", "action"])
        drafts_df["year"] = year
        dfs[file_name]["main"].append(drafts_df) 

async def process_eco_rounds(file, file_name, table_name, year, dfs, reference_ids, pool):
    eco_rounds_df = csv_to_df(file)
    eco_rounds_df = await new_data(eco_rounds_df, table_name, year, pool)
    if len(eco_rounds_df.index) > 0:
        eco_rounds_df = convert_reference_columns_to_category(eco_rounds_df)
        eco_rounds_df = await change_reference_name_to_id(eco_rounds_df, year, reference_ids)
        eco_rounds_df = k_to_numeric(eco_rounds_df, "Loadout Value")
        eco_rounds_df = k_to_numeric(eco_rounds_df, "Remaining Credits")
        eco_rounds_df = get_eco_type(eco_rounds_df)
        eco_rounds_df = drop_columns(eco_rounds_df)
        eco_rounds_df = rename_columns(eco_rounds_df)
        eco_rounds_df = reorder_columns(eco_rounds_df, ["tournament_id", "stage_id", "match_type_id", "match_id", "team_id",
                                                    "map_id", "round_number", "loadout_value", "remaining_credits", "type", "outcome"])
        eco_rounds_df["year"] = year
        dfs[file_name]["main"].append(eco_rounds_df)
      
async def process_eco_stats(file, file_name, table_name, year, dfs, reference_ids, pool):
    eco_stats_df = csv_to_df(file)
    eco_stats_df = await new_data(eco_stats_df, table_name, year, pool)
    if len(eco_stats_df.index) > 0:
        eco_stats_df = convert_reference_columns_to_category(eco_stats_df)
        eco_stats_df = await change_reference_name_to_id(eco_stats_df, year, reference_ids)
        eco_stats_df = convert_missing_numbers(eco_stats_df)
        eco_stats_df = drop_columns(eco_stats_df)
        eco_stats_df = rename_columns(eco_stats_df)
        eco_stats_df = reorder_columns(eco_stats_df, ["tournament_id", "stage_id", "match_type_id", "match_id", "team_id", "map_id", "type", "initiated", "won"])
        eco_stats_df = convert_to_ints(eco_stats_df)
        eco_stats_df["year"] = year
        dfs[file_name]["main"].append(eco_stats_df)
   
      

async def process_kills(file, file_name, table_name, year, dfs, reference_ids, pool):
    kills_df = csv_to_df(file)
    kills_df = await new_data(kills_df, table_name, year, pool)
    if len(kills_df.index) > 0:
        kills_df = remove_nan_rows(kills_df, ['Player Kills', 'Enemy Kills', 'Difference'])
        kills_df = remove_leading_zeroes_from_players(kills_df)
        kills_df = convert_reference_columns_to_category(kills_df)
        kills_df = await change_reference_name_to_id(kills_df, year, reference_ids)
        kills_df = convert_missing_numbers(kills_df)
        kills_df = drop_columns(kills_df)
        kills_df = rename_columns(kills_df)
        kills_df = reorder_columns(kills_df, ["tournament_id", "stage_id", "match_type_id", "match_id", "player_team_id", "player_id", "enemy_team_id", "enemy_id",
                                                "map_id", "player_kills", "enemy_kills", "difference", "kill_type"])
        kills_df = convert_to_ints(kills_df)
        kills_df["year"] = year
        dfs[file_name]["main"].append(kills_df)

async def process_kills_stats(file, file_name, table_name, year, dfs, reference_ids, pool):
    kills_stats_df = csv_to_df(file)
    kills_stats_df = await new_data(kills_stats_df, table_name, year, pool)
    if len(kills_stats_df.index) > 0:
        kills_stats_df = remove_leading_zeroes_from_players(kills_stats_df)
        kills_stats_df = add_player_nan(kills_stats_df)
        kills_stats_df = convert_reference_columns_to_category(kills_stats_df)
        kills_stats_df = await change_reference_name_to_id(kills_stats_df, year, reference_ids)
        kills_stats_df = convert_missing_numbers(kills_stats_df)
        kills_stats_df = drop_columns(kills_stats_df)
        kills_stats_df = rename_columns(kills_stats_df)
        kills_stats_df = reorder_columns(kills_stats_df, ["tournament_id", "stage_id", "match_type_id", "match_id", "team_id", "player_id", "map_id", "agents",
                                                            "two_kills", "three_kills", "four_kills", "five_kills", "one_vs_one", "one_vs_two", "one_vs_three",
                                                            "one_vs_four", "one_vs_five", "econ", "spike_plants", "spike_defuses"])
        kills_stats_df = convert_to_ints(kills_stats_df)
        kills_stats_df["year"] = year
        dfs[file_name]["main"].append(kills_stats_df)

async def process_kills_stats_agents(combined_dfs, combined_df, reference_ids):
    if len(combined_df.index) > 0:
        agents_df = combined_df[["index", "agents", "year"]]
        agents_df = splitting_agents(agents_df)
        agents_df.rename(columns={"agents": "Agent"}, inplace=True)
        agents_df = await change_reference_name_to_id(agents_df, 0, reference_ids)
        combined_df.drop(columns="agents", inplace=True)
        agents_df.drop(columns="Agent", inplace=True)
        agents_df = convert_to_ints(agents_df)
        agents_df = rename_columns(agents_df)
        agents_df = reorder_columns(agents_df, ["index", "agent_id", "year"])
        combined_dfs["kills_stats.csv"]["agents"] = pd.concat([combined_dfs["kills_stats.csv"]["agents"], agents_df], ignore_index=True)


async def process_maps_played(file, file_name, table_name, year, dfs, reference_ids, pool):
    maps_played_df = csv_to_df(file)
    maps_played_df = await new_data(maps_played_df, table_name, year, pool)
    if len(maps_played_df.index) > 0:
        maps_played_df = convert_reference_columns_to_category(maps_played_df)
        maps_played_df = await change_reference_name_to_id(maps_played_df, year, reference_ids)
        maps_played_df = drop_columns(maps_played_df)
        maps_played_df = rename_columns(maps_played_df)
        maps_played_df = reorder_columns(maps_played_df, ["tournament_id", "stage_id", "match_type_id", "match_id", "map_id"])
        maps_played_df["year"] = year
        dfs[file_name]["main"].append(maps_played_df)

async def process_maps_scores(file, file_name, table_name, year, dfs, reference_ids, pool):
    maps_scores_df = csv_to_df(file)
    maps_scores_df = await new_data(maps_scores_df, table_name, year, pool)
    if len(maps_scores_df.index) > 0:
        maps_scores_df = convert_reference_columns_to_category(maps_scores_df)
        maps_scores_df = await change_reference_name_to_id(maps_scores_df, year, reference_ids)
        maps_scores_df = drop_columns(maps_scores_df)
        maps_scores_df = standardized_duration(maps_scores_df)
        maps_scores_df = convert_missing_numbers(maps_scores_df)
        maps_scores_df = rename_columns(maps_scores_df)
        maps_scores_df = reorder_columns(maps_scores_df, ["tournament_id", "stage_id", "match_type_id", "match_id", "map_id", "team_a_id",
                                                            "team_b_id", "team_a_score", "team_a_attacker_score", "team_a_defender_score",
                                                            "team_a_overtime_score", "team_b_score", "team_b_attacker_score",
                                                            "team_b_defender_score", "team_b_overtime_score", "duration"])
        maps_scores_df = convert_to_ints(maps_scores_df)
        maps_scores_df["year"]= year
        dfs[file_name]["main"].append(maps_scores_df)


async def process_overview(file, file_name, table_name, year, dfs, reference_ids, pool):
    overview_df = csv_to_df(file)
    overview_df = await new_data(overview_df, table_name, year, pool)
    if len(overview_df.index) > 0:
        overview_df = remove_nan_rows(overview_df, ["Rating", "Average Combat Score", "Kills", "Deaths", "Assists", "Kills - Deaths (KD)", "Kill, Assist, Trade, Survive %",
                                                        "Average Damage Per Round", "Headshot %", "First Kills"	, "First Deaths", "Kills - Deaths (FKD)"])
        overview_df = remove_leading_zeroes_from_players(overview_df)
        overview_df = add_player_nan(overview_df)
        overview_df = convert_reference_columns_to_category(overview_df)
        overview_df = await change_reference_name_to_id(overview_df, year, reference_ids)
        overview_df = drop_columns(overview_df)
        overview_df = convert_percentages_to_decimal(overview_df)
        overview_df = convert_missing_numbers(overview_df)
        overview_df = rename_columns(overview_df)
        overview_df = reorder_columns(overview_df, ["tournament_id", "stage_id", "match_type_id", "match_id", "map_id", "player_id",  "team_id",
                                                    "agents", "rating", "acs", "kills", "deaths", "assists", "kd", "kast", "adpr", "headshot", "fk",
                                                    "fd", "fkd", "side"])
        overview_df = convert_to_ints(overview_df)
        overview_df["year"] = year
        dfs[file_name]["main"].append(overview_df)

async def process_overview_agents(combined_dfs, combined_df, reference_ids):
    if len(combined_df.index) > 0:
        agents_df = combined_df[["index", "agents", "year"]]
        agents_df = splitting_agents(agents_df)
        agents_df.rename(columns={"agents": "Agent"}, inplace=True)
        combined_df.drop(columns="agents", inplace=True)
        agents_df = await change_reference_name_to_id(agents_df, 0, reference_ids)
        agents_df.drop(columns="Agent", inplace=True)
        agents_df = rename_columns(agents_df)
        agents_df = reorder_columns(agents_df, ["index", "agent_id", "year"])
        agents_df = convert_to_ints(agents_df)
        combined_dfs["overview.csv"]["agents"] = pd.concat([combined_dfs["overview.csv"]["agents"], agents_df], ignore_index=True)

async def process_rounds_kills(file, file_name, table_name, year, dfs, reference_ids, pool):
    rounds_kills_df = csv_to_df(file)
    rounds_kills_df = await new_data(rounds_kills_df, table_name, year, pool)
    if len(rounds_kills_df.index) > 0:
        rounds_kills_df = remove_leading_zeroes_from_players(rounds_kills_df)
        rounds_kills_df = convert_reference_columns_to_category(rounds_kills_df)
        rounds_kills_df = await change_reference_name_to_id(rounds_kills_df, year, reference_ids)
        rounds_kills_df = drop_columns(rounds_kills_df)
        rounds_kills_df = rename_columns(rounds_kills_df)
        rounds_kills_df = reorder_columns(rounds_kills_df, ["tournament_id", "stage_id", "match_type_id", "match_id",
                                                            "map_id", "eliminator_team_id", "eliminated_team_id",
                                                            "eliminator_id", "eliminated_id", "eliminator_agent_id", "eliminated_agent_id",
                                                            "round_number", "kill_type"])
        rounds_kills_df["year"] = year
        dfs[file_name]["main"].append(rounds_kills_df)


async def process_scores(file, file_name, table_name, year, dfs, reference_ids, pool):
    scores_df = csv_to_df(file)
    scores_df = await new_data(scores_df, table_name, year, pool)
    if len(scores_df.index) > 0:
        scores_df = convert_reference_columns_to_category(scores_df)
        scores_df = await change_reference_name_to_id(scores_df, year, reference_ids)
        scores_df = drop_columns(scores_df)
        scores_df = rename_columns(scores_df)
        scores_df = reorder_columns(scores_df, ["tournament_id", "stage_id", "match_type_id", "match_id", "team_a_id", "team_b_id",
                                                    "team_a_score", "team_b_score", "match_result"])
        scores_df["year"] = year
        dfs[file_name]["main"].append(scores_df)


async def process_win_loss_methods_count(file, file_name, table_name, year, dfs, reference_ids, pool):
    win_loss_methods_count_df = csv_to_df(file)
    win_loss_methods_count_df = await new_data(win_loss_methods_count_df, table_name, year, pool)
    if len(win_loss_methods_count_df.index) > 0:
        win_loss_methods_count_df = convert_reference_columns_to_category(win_loss_methods_count_df)
        win_loss_methods_count_df = await change_reference_name_to_id(win_loss_methods_count_df, year, reference_ids)
        win_loss_methods_count_df = drop_columns(win_loss_methods_count_df)
        win_loss_methods_count_df = rename_columns(win_loss_methods_count_df)
        win_loss_methods_count_df = reorder_columns(win_loss_methods_count_df, ["tournament_id", "stage_id", "match_type_id", "match_id", "team_id",
                                                                                "map_id", 'elimination', 'detonated', 'defused', 'time_expiry_no_plant', "eliminated",
                                                                                'defused_failed', 'detonation_denied', 'time_expiry_failed_to_plant'])
        win_loss_methods_count_df["year"] = year
        dfs[file_name]["main"].append(win_loss_methods_count_df)
   

async def process_win_loss_methods_round_number(file, file_name, table_name, year, dfs, reference_ids, pool):
    win_loss_methods_round_number_df = csv_to_df(file)
    win_loss_methods_round_number_df = await new_data(win_loss_methods_round_number_df, table_name, year, pool)
    if len(win_loss_methods_round_number_df.index) > 0:
        win_loss_methods_round_number_df = convert_reference_columns_to_category(win_loss_methods_round_number_df)
        win_loss_methods_round_number_df = await change_reference_name_to_id(win_loss_methods_round_number_df, year, reference_ids)
        win_loss_methods_round_number_df = drop_columns(win_loss_methods_round_number_df)
        win_loss_methods_round_number_df = rename_columns(win_loss_methods_round_number_df)
        win_loss_methods_round_number_df = reorder_columns(win_loss_methods_round_number_df, ["tournament_id", "stage_id", "match_type_id", "match_id", "team_id",
                                                                                                "map_id", "round_number", "method", "outcome"])
        win_loss_methods_round_number_df["year"] = year
        dfs[file_name]["main"].append(win_loss_methods_round_number_df)

async def process_agents_pick_rates(file, file_name, table_name, year, dfs, reference_ids, pool):
    agents_pick_rates_df = csv_to_df(file)
    agents_pick_rates_df = await new_data(agents_pick_rates_df, table_name, year, pool)
    if len(agents_pick_rates_df.index) > 0:
        agents_pick_rates_df = convert_reference_columns_to_category(agents_pick_rates_df)
        agents_pick_rates_df = await change_reference_name_to_id(agents_pick_rates_df, year, reference_ids)
        agents_pick_rates_df = drop_columns(agents_pick_rates_df)
        agents_pick_rates_df = convert_percentages_to_decimal(agents_pick_rates_df)
        agents_pick_rates_df = rename_columns(agents_pick_rates_df)
        agents_pick_rates_df = reorder_columns(agents_pick_rates_df, ["tournament_id", "stage_id", "match_type_id", "map_id", "agent_id",
                                                                        "pick_rate"])
        agents_pick_rates_df["year"] = year
        dfs[file_name]["main"].append(agents_pick_rates_df)


async def process_maps_stats(file, file_name, table_name, year, dfs, reference_ids, pool):
    maps_stats_df = csv_to_df(file)
    maps_stats_df = await new_data(maps_stats_df, table_name, year, pool)
    if len(maps_stats_df.index) > 0:
        maps_stats_df = convert_reference_columns_to_category(maps_stats_df)
        maps_stats_df = await change_reference_name_to_id(maps_stats_df, year, reference_ids)
        maps_stats_df = drop_columns(maps_stats_df)
        maps_stats_df = convert_percentages_to_decimal(maps_stats_df)
        maps_stats_df = rename_columns(maps_stats_df)
        maps_stats_df = reorder_columns(maps_stats_df, ["tournament_id", "stage_id", "match_type_id", "map_id", "total_maps_played",
                                                        "attacker_side_win_percentage", "defender_side_win_percentage"])
        maps_stats_df['year'] = year
        dfs[file_name]["main"].append(maps_stats_df)

async def process_teams_picked_agents(file, file_name, table_name, year, dfs, reference_ids, pool):
    teams_picked_agents_df = csv_to_df(file)
    teams_picked_agents_df = await new_data(teams_picked_agents_df, table_name, year, pool)
    if len(teams_picked_agents_df.index) > 0:
        teams_picked_agents_df = convert_reference_columns_to_category(teams_picked_agents_df)
        teams_picked_agents_df = await change_reference_name_to_id(teams_picked_agents_df, year, reference_ids)
        teams_picked_agents_df = drop_columns(teams_picked_agents_df)
        teams_picked_agents_df = rename_columns(teams_picked_agents_df)
        teams_picked_agents_df = reorder_columns(teams_picked_agents_df, ["tournament_id", "stage_id", "match_type_id", "team_id", "map_id",
                                                                            "agent_id", "total_wins_by_map", "total_loss_by_map", "total_maps_played"])
        teams_picked_agents_df["year"] = year
        dfs[file_name]["main"].append(teams_picked_agents_df)



async def process_players_stats(file, file_name, table_name, year, dfs, reference_ids, pool):
    players_stats_df = csv_to_df(file)
    players_stats_df = await new_data(players_stats_df, table_name, year, pool)
    if len(players_stats_df.index) > 0:
        players_stats_df = remove_leading_zeroes_from_players(players_stats_df)
        players_stats_df = add_player_nan(players_stats_df)
        players_stats_df = convert_reference_columns_to_category(players_stats_df)
        players_stats_df = await change_reference_name_to_id(players_stats_df, year, reference_ids)
        players_stats_df = convert_clutches(players_stats_df)
        players_stats_df = drop_columns(players_stats_df)
        players_stats_df = convert_percentages_to_decimal(players_stats_df)
        players_stats_df = rename_columns(players_stats_df)
        players_stats_df = reorder_columns(players_stats_df, ["tournament_id", "stage_id", "match_type_id", "player_id", "teams", "agents", "rounds_played",
                                                                "rating", "acs", "kd", "kast", "adr", "kpr", "apr", "fkpr", "fdpr", "headshot",
                                                                "clutch_success", "clutches_won", "clutches_played", "mksp", "kills", "deaths", "assists",
                                                                "fk", "fd"])
        players_stats_df = convert_to_ints(players_stats_df)
        players_stats_df["year"] = year

        dfs[file_name]["main"].append(players_stats_df)


async def process_players_stats_agents(combined_dfs, combined_df, reference_ids):
    if len(combined_df.index) > 0:
        agents_df = combined_df[["index", "agents", "year"]]
        agents_df = splitting_agents(agents_df)
        agents_df.rename(columns={"agents": "Agent"}, inplace=True)
        agents_df = await change_reference_name_to_id(agents_df, 0, reference_ids)
        combined_df.drop(columns="agents", inplace=True)
        agents_df.drop(columns="Agent", inplace=True)
        agents_df = convert_to_ints(agents_df)
        agents_df = rename_columns(agents_df)
        agents_df = reorder_columns(agents_df, ["index", "agent_id", "year"])
        combined_dfs["players_stats.csv"]["agents"] = pd.concat([combined_dfs["players_stats.csv"]["agents"], agents_df], ignore_index=True)


async def process_players_stats_teams(combined_dfs, combined_df, reference_ids):
    if len(combined_df.index) > 0:
        teams_df = combined_df[["index", "teams", "year"]]
        teams_df = splitting_teams(teams_df)
        teams_df.rename(columns={"teams": "Team"}, inplace=True)
        combined_df.drop(columns="teams", inplace=True)
        teams_df = await change_reference_name_to_id(teams_df, 0, reference_ids)
        teams_df.drop(columns="Team", inplace=True)
        teams_df = convert_to_ints(teams_df)
        teams_df = rename_columns(teams_df)
        teams_df = reorder_columns(teams_df, ["index", "team_id", "year"])
        combined_dfs["players_stats.csv"]["teams"] = pd.concat([combined_dfs["players_stats.csv"]["teams"], teams_df], ignore_index=True)
    


async def process_csv_file(csv_file, year, dfs, reference_ids, pool, semaphore):
    file_name = csv_file.split("/")[-1]
    table_name = file_name.split(".")[0]
    async with semaphore:
        print(file_name, year)
        match file_name:
            case "draft_phase.csv":
                await process_drafts(csv_file, file_name, table_name, year, dfs, reference_ids, pool)
            case "eco_rounds.csv":
                await process_eco_rounds(csv_file, file_name, table_name, year, dfs, reference_ids, pool)
            case "eco_stats.csv": 
                await process_eco_stats(csv_file, file_name, table_name, year, dfs, reference_ids, pool)
            case "kills.csv":
                await process_kills(csv_file, file_name, table_name, year, dfs, reference_ids, pool)
            case "kills_stats.csv":
                await process_kills_stats(csv_file, file_name, table_name, year, dfs, reference_ids, pool)
            case "maps_played.csv":
                await process_maps_played(csv_file, file_name, table_name, year, dfs, reference_ids, pool)
            case "maps_scores.csv":
                await process_maps_scores(csv_file, file_name, table_name, year, dfs, reference_ids, pool)
            case "overview.csv":
                await process_overview(csv_file, file_name, table_name, year, dfs, reference_ids, pool)
            case "rounds_kills.csv":
                await process_rounds_kills(csv_file, file_name, table_name, year, dfs, reference_ids, pool)
            case "scores.csv":
                await process_scores(csv_file, file_name, table_name, year, dfs, reference_ids, pool)
            case "win_loss_methods_count.csv":
                await process_win_loss_methods_count(csv_file, file_name, table_name, year, dfs, reference_ids, pool)
            case "win_loss_methods_round_number.csv":
                await process_win_loss_methods_round_number(csv_file, file_name, table_name, year, dfs, reference_ids, pool)
            case "agents_pick_rates.csv":
                await process_agents_pick_rates(csv_file, file_name, table_name, year, dfs, reference_ids, pool)
            case "maps_stats.csv":
                await process_maps_stats(csv_file, file_name, table_name, year, dfs, reference_ids, pool)
            case "teams_picked_agents.csv":
                await process_teams_picked_agents(csv_file, file_name, table_name, year, dfs, reference_ids, pool)
            case "players_stats.csv":
                await process_players_stats(csv_file, file_name, table_name, year, dfs, reference_ids, pool)
    

async def process_csv_files(csv_files, year, dfs, reference_ids, pool, semaphore):
    await asyncio.gather(
        *(process_csv_file(csv_file, year, dfs, reference_ids, pool, semaphore) for csv_file in csv_files)
    )

async def process_years(csv_files_w_years, dfs, reference_ids, pool):
    sem = asyncio.Semaphore(10)
    await asyncio.gather(
        *(process_csv_files(csv_files, year, dfs, reference_ids, pool, sem) for year, csv_files in csv_files_w_years.items())
    )
