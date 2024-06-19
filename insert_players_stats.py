import os
from Connect.connect import connect, engine
from datetime import datetime
from initialization.create_tables import create_all_tables
import asyncio
from initialization.add_data import *
from find_csv_files.find_csv_files import find_csv_files
from Connect.config import config

async def main():
    start_time = time.time()
    now = datetime.now()
    years = [2021, 2022, 2023, 2024]
    conn, curr = connect()
    sql_alchemy_engine = engine()
    db_conn_info = config()

    csv_files = [find_csv_files(f"{os.getcwd()}/vct_{year}/players_stats", "players_stats", year) for year in years]
    print(csv_files)
    combined_dfs = {}
    dfs = {}
    csv_files_w_years = {year: csv_files[i] for i, year in enumerate(years)}
    for path_list in csv_files:
        for file_path in path_list:
            file_name = file_path.split("/")[-1]
            dfs[file_name] = {"agents": [], "teams": [], "main": []}
            combined_dfs[file_name] = {"agents": pd.DataFrame(), "teams": pd.DataFrame(), "main": pd.DataFrame()}

    # await add_players_stats(csv_files[2][0], years[2], sql_alchemy_engine)
    await process_years(csv_files_w_years, dfs)
    combine_dfs(combined_dfs, dfs)

    await process_players_stats_agents(combined_dfs, combined_dfs["players_stats.csv"]["main"])
    await process_players_stats_teams(combined_dfs, combined_dfs["players_stats.csv"]["main"])


    await add_data(combined_dfs, sql_alchemy_engine)

    end_time = time.time()
    elasped_time = end_time - start_time
    hours, remainder = divmod(elasped_time, 3600)
    minutes, seconds = divmod(remainder, 60)
    print(f"Time: {int(hours)} hours, {int(minutes)} minutes, {int(seconds)} seconds")
    # rounds_kills = pd.read_csv("matches/rounds_kills.csv")

    # conn.commit()
    # curr.close()
    # conn.close()

if __name__ == '__main__':
    asyncio.run(main())