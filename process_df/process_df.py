import pandas as pd
from checking.check_values import check_na
from retrieve.retrieve import retrieve_primary_key
from Connect.connect import create_pool, create_db_url
import asyncpg
import asyncio
import numpy as np
import sys

# na_values = ['', '#N/A', '#N/A N/A', '#NA', '-1.#IND',
#             '-1.#QNAN', '-NaN', '-nan', '1.#IND',
#             '1.#QNAN', 'N/A', 'NULL', 'NaN',
#             'n/a', 'null']

def strip_white_space(df, column_name):
    df.loc[:, column_name] = df[column_name].str.strip()

def create_ids(df):
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

def convert_percentages(df):
    columns = [ "Kill, Assist, Trade, Survive %", "Headshot %"]
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

def get_eco_type(df, column):
    df[column] = df[column].str.split(":").str[0]
    return df

def convert_to_category(df):
    columns = ["Tournament", "Stage", "Match Type", "Match Name", "Agents", "Eliminator", "Eliminated", "Eliminator Team", "Eliminated Team",
               "Eliminator Agent", "Eliminated Agent", "Team A", "Team B", "Player Team", "Enemy Team", "Team", "Player", "Player Team",
               "Map"]
    for column in columns:
        if column in df:
            df[column] = df[column].astype("category")
    return df

def drop_columns(df):
    columns = ["Tournament", "Stage", "Match Type", "Match Name", "Team", "Map", "Player", "Player Team", "Enemy Team", "Enemy",
               "Team A", "Team B", "Eliminator", "Eliminator Team", "Eliminated", "Eliminated Team"]
    for column in columns:
        if column in df:
            df.drop(columns=column, inplace=True)
    return df

def reorder_columns(df, column_names):
    return df.reindex(columns=column_names)

def rename_columns(df):
    stats_columns = {"Average Combat Score": "acs", "Kills - Deaths (KD)": "kd", "Kill, Assist, Trade, Survive %": "kast",
                     "Average Damage Per Round": "adpr", "Headshot %": "headshot", "First Kills": "fk", "First Deaths": "fd",
                     "Kills - Deaths (FKD)": "fkd", "Kills:Deaths": "fd", "Kills Per Round": "kpr", "Assists Per Round": "apr",
                     "First Kills Per Round": "fkpr", "First Deaths Per Round": "fdpr", "Clutch Success %": "clutch_success",
                     "Clutches (won/played)": "clutches", "Maximum Kills in a Single Map": "mksp"}
    for column in df.columns:
        if column in stats_columns:
            new_column_name = stats_columns[column]
        else:    
            new_column_name = column.lower().replace(" ", "_")
        df.rename(columns={column: new_column_name}, inplace=True)
    return df

def csv_to_df(file):
    return pd.read_csv(file)

def create_tuples(df):
    tuples = [tuple(x) for x in df.values]
    return tuples

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

def flatten_list_of_dicts(list_of_dicts):
    conditional_mapping = {}
    for dictionary in list_of_dicts:
        conditional_mapping.update(dictionary)
    return conditional_mapping


def create_conditions_values_1d(df, ids, column):
    conditions, values = [], []
    for key, value in ids.items():
        conditions.append(df[column] == key)
        values.append(value)
    return conditions, values


def create_stages_conditions_values(df, ids):
    conditions = []
    values = []
    for key, value in ids.items():
        conditions.append((df["Tournament ID"] == key[0]) & (df["Stage"] == key[1]))
        values.append(value)
    return conditions, values

def create_match_types_conditions_values(df, ids):
    conditions = []
    values = []
    for key, value in ids.items():
        conditions.append((df["Tournament ID"] == key[0]) & (df["Stage ID"] == key[1]) & (df["Match Type"] == key[2]))
        values.append(value)
    return conditions, values

def create_matches_conditions_values(df, ids):
    conditions = []
    values = []
    for key, value in ids.items():
        conditions.append((df["Tournament ID"] == key[0]) & (df["Stage ID"] == key[1]) & (df["Match Type ID"] == key[2]) & (df["Match Name"] == key[3]))
        values.append(value)
    return conditions, values

async def process_column(conn, df, column, id_name, table_name, value_name):
    values = df[column].unique().tolist()
    ids = [await retrieve_primary_key(conn, id_name, table_name, value_name, value) for value in values if pd.notna(value)]
    ids = flatten_list_of_dicts(ids)
    conditions, result_values = create_conditions_values_1d(df, ids, column)
    df[f"{column} ID"] = np.select(conditions, result_values)
    if table_name == "players":
        df[f"{column} ID"] = df[f"{column} ID"].astype("UInt32")
    else:
        df[f"{column} ID"] = df[f"{column} ID"].astype("UInt16")

async def process_tournaments_stages_match_types_matches(pool, df, year):
    async with pool.acquire() as conn:
        if "Tournament" in df:
            tournaments = df["Tournament"].unique().tolist()
            tournament_ids = [await retrieve_primary_key(pool, "tournament_id", "tournaments", "tournament", tournament, year) for tournament in tournaments]
            tournament_ids = flatten_list_of_dicts(tournament_ids)
            conditions, values = create_conditions_values_1d(df, tournament_ids, "Tournament")
            df["Tournament ID"] = np.select(conditions, values)
            if "Stage" in df:
                stages = df[["Tournament ID", "Stage"]].drop_duplicates()
                tuples = create_tuples(stages)
                stage_ids = [await retrieve_primary_key(conn, "stage_id", "stages", "stage", (tournament_id, stage), year) 
                            for tournament_id, stage in tuples]
                stage_ids = flatten_list_of_dicts(stage_ids)
                conditions, values = create_stages_conditions_values(df, stage_ids)
                df["Stage ID"] = np.select(conditions, values)
                if "Match Type" in df:
                    match_types = df[["Tournament ID", "Stage ID", "Match Type"]].drop_duplicates()
                    tuples = create_tuples(match_types)
                    match_types_ids = [await retrieve_primary_key(conn, "match_type_id", "match_types", "match_type", (tournament_id, stage_id, match_type), year) 
                                        for tournament_id, stage_id, match_type in tuples]
                    match_types_ids = flatten_list_of_dicts(match_types_ids)
                    conditions, values = create_match_types_conditions_values(df, match_types_ids)
                    df["Match Type ID"] = np.select(conditions, values)
                if "Match Name" in df:
                    matches = df[["Tournament ID", "Stage ID", "Match Type ID", "Match Name"]].drop_duplicates()
                    tuples = create_tuples(matches)
                    matches_id = [await retrieve_primary_key(conn, "match_id", "matches", "match", (tournament_id, stage_id, match_type_id, match_name), year)
                                    for tournament_id, stage_id, match_type_id, match_name in tuples]
                    matches_id = flatten_list_of_dicts(matches_id)
                    conditions, values = create_matches_conditions_values(df, matches_id)
                    df["Match ID"] = np.select(conditions, values)


async def process_teams(pool, df):
    async with pool.acquire() as conn:
        team_columns = ["Team", "Player Team", "Enemy Team", "Eliminator Team", "Eliminated Team", "Team A", "Team B"]
        tasks = [await process_column(conn, df, column, "team_id", "teams", "team") for column in team_columns if column in df]
        # await asyncio.gather(*tasks)

async def process_players(pool, df):
    async with pool.acquire() as conn:
        player_columns = ["Player", "Enemy", "Eliminator", "Eliminated"]
        tasks = [await process_column(conn, df, column, "player_id", "players", "player") for column in player_columns if column in df]
        # await asyncio.gather(*tasks)

async def process_agents(pool, df):
    async with pool.acquire() as conn:
        agent_columns = ["agent", "Eliminator Agent", "Eliminated Agent"]
        tasks = [await process_column(conn, df, column, "agent_id", "agents", "agent") for column in agent_columns if column in df]

async def process_maps(pool, df):
    async with pool.acquire() as conn:
        map_columns = ["Map"]
        tasks = [await process_column(conn, df, column, "map_id", "maps", "map") for column in map_columns if column in df]

async def change_reference_name_to_id(df, year):
    db_url = create_db_url()
    async with asyncpg.create_pool(db_url) as pool:
        await asyncio.gather(
            process_tournaments_stages_match_types_matches(pool, df, year),
            process_players(pool, df),
            process_teams(pool, df),
            process_maps(pool, df),
            process_agents(pool, df)
        )

    return df
