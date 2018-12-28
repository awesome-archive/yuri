import os
import random

from utils import *

import cv2
import numpy as np

import sc2
from sc2 import run_game, Race, maps, Difficulty, position
from sc2.player import Bot, Computer
from sc2.constants import NEXUS, PROBE, PYLON, ASSIMILATOR, GATEWAY, \
    CYBERNETICSCORE, STALKER, STARGATE, VOIDRAY, OBSERVER, ROBOTICSFACILITY
from examples.protoss.cannon_rush import CannonRushBot


BUILD_PYLON_SUPPLY_LEFT = 5
NEXUS_MAX = 3
OFFENCE_AMOUNT = 15
DEFENCE_AMOUNT = 3

class MainBot(sc2.BotAI):
    def __init__(self):
        self.IPS = 165  # probable Iteration Per Second
        self.MAX_WORKERS = 65
        self.do_something_after = 0
        self.train_data = []
        self.headless = False

    async def on_step(self, iteration):
        """
        actions will be made every step 
        """
        self.iteration = iteration
        await self.intel()
        await self.distribute_workers()
        await self.build_workers()
        await self.build_pylons()
        await self.build_assimilators()
        await self.expand()
        await self.offensive_force_building()
        await self.build_offensive_force()
        await self.attack()
        # await self.scout()

    def on_end(self, game_result):
        """
        save training data if win
        """
        print('--- on_end called ---')
        print(game_result)

        if game_result == Result.Victory:
            np.save("train_data/{}.npy".format(str(int(time.time()))), np.array(self.train_data))

    async def intel(self, headless=None):
        """
        convert data into OpenGL images
        """
        game_data = np.zeros(
            (self.game_info.map_size[1], self.game_info.map_size[0], 3),
            dtype=np.uint8
        )

        # draw bot units
        draw_dict = {
            NEXUS: [15, (0, 255, 0)],
            PYLON: [3, (20, 235, 0)],
            PROBE: [1, (55, 200, 0)],
            ASSIMILATOR: [2, (55, 200, 0)],
            OBSERVER: [1, (255, 255, 255)],
            GATEWAY: [3, (200, 100, 0)],
            CYBERNETICSCORE: [3, (150, 150, 0)],
            ROBOTICSFACILITY: [5, (215, 155, 0)],
            STARGATE: [5, (255, 0, 0)],
            VOIDRAY: [3, (255, 100, 0)]
        }
        for unit_type in draw_dict:
            for unit in self.units(unit_type):
                pos = unit.position
                cv2.circle(
                    game_data,
                    (int(pos[0]), int(pos[1])),
                    draw_dict[unit_type][0],
                    draw_dict[unit_type][1],
                    -1
                )

        # draw enemy buildings
        main_base_names = ['nexus', 'commandcenter', 'hatchery']
        for enemy_building in self.known_enemy_structures:
            pos = enemy_building.position
            if enemy_building.name.lower() in main_base_names:
                cv2.circle(
                    game_data,
                    (int(pos[0]), int(pos[1])),
                    15,
                    (0, 0, 255),
                    -1
                )
            else:
                cv2.circle(
                    game_data,
                    (int(pos[0]), int(pos[1])),
                    5,
                    (200, 50, 212),
                    -1
                )
        
        # draw enemy units
        for enemy_unit in self.known_enemy_units:
            if not enemy_unit.is_structure:
                worker_names = ['probe', 'scv', 'drone']
                pos = enemy_unit.position
                # draw workers
                if enemy_unit.name.lower() in worker_names:
                    cv2.circle(
                        game_data, 
                        (int(pos[0]), int(pos[1])), 
                        1, 
                        (55, 0, 155), 
                        -1
                    )
                # draw else
                else:
                    cv2.circle(
                        game_data, 
                        (int(pos[0]), int(pos[1])), 
                        3, 
                        (50, 0, 215), 
                        -1
                    )

        # draw mineral, vespene lines
        line_max = 50
        mineral_ratio = min([self.minerals / 1500, 1.0])
        vespene_ratio = min([self.vespene / 1500, 1.0])
        population_ratio = min([self.supply_left / self.supply_cap, 1.0])
        plausible_supply = self.supply_cap / 200
        military_ratio = min([
            (len(self.units(VOIDRAY))+len(self.units(STALKER))) /
            (self.supply_cap - self.supply_left),
            1.0
        ])
        cv2.line(game_data, (0, 19), (int(line_max*military_ratio), 19), (250, 250, 200), 3) # worker & supply
        cv2.line(game_data, (0, 15), (int(line_max*plausible_supply), 15), (220, 200, 200), 3)
        cv2.line(game_data, (0, 11), (int(line_max*population_ratio), 11), (150, 150, 150), 3)
        cv2.line(game_data, (0, 7), (int(line_max*vespene_ratio), 7), (210, 200, 0), 3)
        cv2.line(game_data, (0, 3), (int(line_max*mineral_ratio), 3), (0, 255, 25), 3)

        flipped = cv2.flip(game_data, 0)

        if not headless:
            resized = cv2.resize(flipped, dsize=None, fx=2, fy=2)
            cv2.imshow('Intel', resized)
            cv2.waitKey(1)

    def random_location_variance(self, enemy_start_location):
        """
        return a random position near enemy start location; used for scouting
        """
        x = enemy_start_location[0]
        y = enemy_start_location[1]

        x *= 1 + random.randrange(-20, 20)/100 # range: 0.8x ~ 1.2x
        y *= 1 + random.randrange(-20, 20)/100 # range: 0.8y ~ 1.2y

        # make the out-of-map positions valid 
        if x < 0:
            x = 0
        if y < 0:
            y = 0
        if x > self.game_info.map_size[0]:
            x = self.game_info.map_size[0]
        if y > self.game_info.map_size[1]:
            y = self.game_info.map_size[1]

        return position.Point2(position.Pointlike((x, y)))

    async def scout(self):
        """
        train scouter if noqueue and can afford
        scout if any scouters available
        """
        if self.units(OBSERVER).amount > 0:
            # scouting
            scout = self.units(OBSERVER)[0]
            if scout.is_idle:
                enemy_location = self.enemy_start_locations[0]
                move_to = self.random_location_variance(enemy_location)
                print(f'scout move to {move_to}')
                await self.do(scout.move(move_to))
        else:
            # tarin scouters
            for rf in self.units(ROBOTICSFACILITY).ready.noqueue:
                if self.can_afford(OBSERVER) and self.supply_left > 0:
                    await self.do(rf.train(OBSERVER))

    async def build_workers(self):
        probe_nums = len(self.units(PROBE))
        if len(self.units(NEXUS)) * 16 > probe_nums and probe_nums < self.MAX_WORKERS:
            for nexus in self.units(NEXUS).ready.noqueue:
                if self.can_afford(PROBE):
                    await self.do(nexus.train(PROBE))

    async def build_pylons(self):
        """
        build pylons near nexuses if needed
        """
        if self.supply_left < BUILD_PYLON_SUPPLY_LEFT and not self.already_pending(PYLON):
            nexuses = self.units(NEXUS).ready
            if nexuses.exists:
                if self.can_afford(PYLON):
                    await self.build(PYLON, near=nexuses.first)

    async def build_assimilators(self):
        """
        build assimilators on vespene geyser near nexuses
        """
        for nexus in self.units(NEXUS).ready:
            vespenes = self.state.vespene_geyser.closer_than(15.0, nexus)
            for vespene in vespenes:
                if not self.can_afford(ASSIMILATOR):
                    break
                worker = self.select_build_worker(vespene.position)
                if worker is None:
                    break
                if not self.units(ASSIMILATOR).closer_than(1.0, vespene).exists:
                    await self.do(worker.build(ASSIMILATOR, vespene))

    async def expand(self):
        """
        build more nuxuses if affordable
        """
        if self.units(NEXUS).amount < NEXUS_MAX and self.can_afford(NEXUS):
            await self.expand_now()

    async def offensive_force_building(self):
        if not self.units(PYLON).ready.exists:
            return
        pylon = self.units(PYLON).ready.random
        if self.units(GATEWAY).ready.exists and not self.units(CYBERNETICSCORE):
            if self.can_afford(CYBERNETICSCORE) and not self.already_pending(CYBERNETICSCORE):
                await self.build(CYBERNETICSCORE, near=pylon)
        elif self.units(GATEWAY).amount == 0:
            if self.can_afford(GATEWAY) and not self.already_pending(GATEWAY):
                await self.build(GATEWAY, near=pylon)
        
        if self.units(CYBERNETICSCORE).ready.exists:
            if len(self.units(STARGATE)) < self.iteration / self.IPS / 2:
                if self.can_afford(STARGATE) and not self.already_pending(STARGATE):
                    await self.build(STARGATE, near=pylon)
            if self.units(ROBOTICSFACILITY).amount == 0:
                if self.can_afford(ROBOTICSFACILITY) and not self.already_pending(ROBOTICSFACILITY):
                    await self.build(ROBOTICSFACILITY, near=pylon)

    async def build_offensive_force(self):
        # train stalkers
        for gw in self.units(GATEWAY).ready.noqueue:
            if self.units(STALKER).amount <= self.units(VOIDRAY).amount \
                    and self.can_afford(STALKER) and self.supply_left > 0:
                await self.do(gw.train(STALKER))

        # train void-rays
        for sg in self.units(STARGATE).ready.noqueue:
            if self.can_afford(VOIDRAY) and self.supply_left > 0:
                await self.do(sg.train(VOIDRAY))

    def find_target(self):
        """
        choose random known enemy units and structures. If none of them is uknown,
        reutrn the location where enemy starts
        """
        if len(self.known_enemy_units) > 0:
            return random.choice(self.known_enemy_units)
        if len(self.known_enemy_structures) > 0:
            return random.choice(self.known_enemy_structures)
        return self.enemy_start_locations[0]

    async def offend(self, units):
        if not isinstance(units, list):
            units = [units]
        for u in units:
            for s in self.units(unit).idle:
                await self.do(s.attack(random.choice(self.known_enemy_units)))
    
    async def defend(self, units):
        if not isinstance(units, list):
            units = [units]
        for u in units:
            for s in self.units(u).idle:
                await self.do(s.attack(self.find_target()))

    async def random_attack(self):
        """
        voidrays choose random enemy units or structures to attack; used for 
        collecting training data
        """
        if len(self.units(VOIDRAY).idle) > 0:
            choice = random.randrange(0, 4)
            target = False
            if self.iteration > self.do_something_after:
                if choice == 0:
                    # no attack
                    wait = random.randrange(20, 165)
                    self.do_something_after = self.iteration + wait

                elif choice == 1:
                    # attack unit closest nexus
                    if len(self.known_enemy_units) > 0:
                        target = self.known_enemy_units.closest_to(random.choice(self.units(NEXUS)))

                elif choice == 2:
                    # attack enemy structures
                    if len(self.known_enemy_structures) > 0:
                        target = random.choice(self.known_enemy_structures)

                elif choice == 3:
                    # attack enemy start
                    target = self.enemy_start_locations[0]

                if target:
                    for vr in self.units(VOIDRAY).idle:
                        await self.do(vr.attack(target))
                y = np.zeros(4)
                y[choice] = 1
                print(y)
                # Training data consits of two tensors, which are random choice
                # array(1*4) and game_data map(176*200*3)
                self.train_data.append([y,self.flipped])

    async def attack(self):
        """
        attack in manally defined order
        """
        if self.headless:
            await random_attack()
        else:
            aggresive_units = {
                STALKER: [15, 3],
                VOIDRAY: [8, 3]
            }
            for unit in aggresive_units:
                if self.units(unit).amount > aggresive_units[unit][0]:
                    await self.offend(unit)
                elif self.units(unit).amount > aggresive_units[unit][1]:
                    await self.defend(unit)


if __name__ == '__main__':
    run_game(maps.get('AbyssalReefLE'), [
        Bot(Race.Protoss, MainBot()),
        Computer(Race.Terran, Difficulty.Hard)
    ], realtime=False)
