import numpy as np

import utils
from glyph import G, C
from level import Level
from strategy import Strategy


class ExplorationLogic:
    def __init__(self, agent):
        self.agent = agent

    # TODO: think how to handle the situation with wizard's tower
    def _level_dfs(self, start, end, path, vis):
        if start in vis:
            return

        if start == end:
            return path

        vis.add(start)
        stairs = self.agent.levels[start].get_stairs(all=True) if start in self.agent.levels else {}
        for k, t in stairs.items():
            if t is None:
                continue
            glyph = self.agent.levels[start].objects[k]
            dir = '>' if glyph in G.STAIR_DOWN else '<' if glyph in G.STAIR_UP else ''
            assert dir, glyph  # TODO: portals

            path.append((k, t, dir))
            r = self._level_dfs(t[0], end, path, vis)
            if r is not None:
                return r
            path.pop()

    def get_path_to_level(self, dungeon_number, level_number):
        return self._level_dfs(self.agent.current_level().key(), (dungeon_number, level_number), [], set())

    def get_achievable_levels(self, dungeon_number=None, level_number=None):
        assert (dungeon_number is None) == (level_number is None)
        if dungeon_number is None:
            dungeon_number, level_number = self.agent.current_level().key()

        vis = set()
        self._level_dfs((dungeon_number, level_number), (-1, -1), [], vis)
        return vis

    def levels_to_explore_to_get_to(self, dungeon_number, level_number, achievable_levels=None):
        if achievable_levels is None:
            achievable_levels = self.get_achievable_levels()

        if len(achievable_levels) == 1:
            return achievable_levels

        if (dungeon_number, level_number) in achievable_levels:
            return set()

        if any((dun == dungeon_number for dun, lev in achievable_levels)):
            closest_level_number = min((lev for dun, lev in achievable_levels if dun == dungeon_number),
                                       key=lambda lev: abs(level_number - lev))
            return {(dungeon_number, closest_level_number)}

        if dungeon_number == Level.GNOMISH_MINES:
            return set.union(*[self.levels_to_explore_to_get_to(Level.DUNGEONS_OF_DOOM, i, achievable_levels)
                               for i in range(2, 5)],
                             {(Level.DUNGEONS_OF_DOOM, i) for i in range(2, 5)
                              if (Level.DUNGEONS_OF_DOOM, i) in achievable_levels})

        if dungeon_number == Level.SOKOBAN:
            return set.union(*[self.levels_to_explore_to_get_to(Level.DUNGEONS_OF_DOOM, i, achievable_levels)
                               for i in range(6, 11)],
                             {(Level.DUNGEONS_OF_DOOM, i) for i in range(6, 11)
                              if (Level.DUNGEONS_OF_DOOM, i) in achievable_levels})

        # TODO: more dungeons

        assert 0, ((dungeon_number, level_number), achievable_levels)

    def get_unexplored_stairs(self, dungeon_number=None, level_number=None, **kwargs):
        assert (dungeon_number is None) == (level_number is None)
        if dungeon_number is None:
            dungeon_number, level_number = self.agent.current_level().key()
        stairs = self.agent.levels[dungeon_number, level_number].get_stairs(**kwargs)
        return [k for k, v in stairs.items() if v is None]

    @Strategy.wrap
    def explore_stairs(self, go_to_strategy, **kwargs):
        unexplored_stairs = self.get_unexplored_stairs(**kwargs)
        if len(unexplored_stairs) == 0:
            yield False
        yield True

        y, x = list(unexplored_stairs)[self.agent.rng.randint(0, len(unexplored_stairs))]
        glyph = self.agent.current_level().objects[y, x]
        dir = '>' if glyph in G.STAIR_DOWN else '<' if glyph in G.STAIR_UP else ''
        assert dir, glyph  # TODO: portals

        go_to_strategy(y, x).run()
        assert (self.agent.blstats.y, self.agent.blstats.x) == (y, x)
        self.agent.move(dir)

    @Strategy.wrap
    def follow_level_path_strategy(self, path, go_to_strategy):
        if not path:
            yield False
        yield True
        for (y, x), _, dir in path:
            go_to_strategy(y, x).run()
            assert (self.agent.blstats.y, self.agent.blstats.x) == (y, x)
            self.agent.move(dir)

    @Strategy.wrap
    def go_to_level_strategy(self, dungeon_number, level_number, go_to_strategy, explore_strategy):
        yield True
        while 1:
            levels_to_search = self.levels_to_explore_to_get_to(dungeon_number, level_number)
            if len(levels_to_search) == 0:
                break

            @Strategy.wrap
            def go_to_random_level_to_explore():
                # TODO: change from random to least explored
                levels_to_search = self.levels_to_explore_to_get_to(dungeon_number, level_number)
                yield True
                if not levels_to_search:
                    return
                random_level = sorted(levels_to_search)[self.agent.rng.randint(0, len(levels_to_search))]
                path = self.get_path_to_level(*random_level)
                assert path is not None
                self.follow_level_path_strategy(path, go_to_strategy).run()
                assert self.agent.current_level().key() == random_level

            for level in sorted(levels_to_search):  # TODO: iteration order
                if len(self.get_unexplored_stairs(*level, all=True)) > 0:
                    path = self.get_path_to_level(*level)
                    self.follow_level_path_strategy(path, go_to_strategy).run()
                    assert self.agent.current_level().key() == level
                    continue

            if self.agent.current_level().key() not in levels_to_search:
                go_to_random_level_to_explore().run()
                assert self.agent.current_level().key() in levels_to_search
                continue

            explore_strategy.preempt(self.agent, [
                self.explore_stairs(go_to_strategy, all=True) \
                        .condition(lambda: self.agent.current_level().key() in levels_to_search),
                go_to_random_level_to_explore().condition(lambda: self.agent.rng.random() < 1 / 500),
            ], continue_after_preemption=False).run()

        path = self.get_path_to_level(dungeon_number, level_number)
        assert path is not None, \
                (self.agent.current_level().key(), (dungeon_number, level_number), self.get_achievable_levels())
        with self.agent.env.debug_log(f'going to level {Level.dungeon_names[dungeon_number]}:{level_number}'):
            self.follow_level_path_strategy(path, go_to_strategy).run()
            assert self.agent.current_level().key() == (dungeon_number, level_number)

    @Strategy.wrap
    def go_to_strategy(self, y, x, *args, **kwargs):
        if self.agent.bfs()[y, x] == -1 or (self.agent.blstats.y, self.agent.blstats.x) == (y, x):
            yield False
        yield True
        return self.agent.go_to(y, x, *args, **kwargs)

    @utils.debug_log('explore1')
    def explore1(self, search_prio_limit=0):
        # TODO: refactor entire function


        def open_neighbor_doors():
            for py, px in self.agent.neighbors(self.agent.blstats.y, self.agent.blstats.x, diagonal=False):
                if self.agent.glyphs[py, px] in G.DOOR_CLOSED:
                    with self.agent.panic_if_position_changes():
                        if not self.agent.open_door(py, px):
                            if not 'locked' in self.agent.message:
                                for _ in range(6):
                                    if self.agent.open_door(py, px):
                                        break
                                else:
                                    while self.agent.glyphs[py, px] in G.DOOR_CLOSED:
                                        self.agent.kick(py, px)
                            else:
                                while self.agent.glyphs[py, px] in G.DOOR_CLOSED:
                                    self.agent.kick(py, px)
                    break

        def to_visit_func():
            level = self.agent.current_level()
            to_visit = np.zeros((C.SIZE_Y, C.SIZE_X), dtype=bool)
            for dy in [-1, 0, 1]:
                for dx in [-1, 0, 1]:
                    if dy != 0 or dx != 0:
                        to_visit |= utils.translate(~level.seen & utils.isin(self.agent.glyphs, G.STONE), dy, dx)
                        if dx == 0 or dy == 0:
                            to_visit |= utils.translate(utils.isin(self.agent.glyphs, G.DOOR_CLOSED), dy, dx)
            return to_visit

        def to_search_func(prio_limit=0, return_prio=False):
            level = self.agent.current_level()
            dis = self.agent.bfs()

            prio = np.zeros((C.SIZE_Y, C.SIZE_X), np.float32)
            prio[:] = -1
            prio -= level.search_count ** 2 * 2
            # is_on_corridor = utils.isin(level.objects, G.CORRIDOR)
            is_on_door = utils.isin(level.objects, G.DOORS)

            stones = np.zeros((C.SIZE_Y, C.SIZE_X), np.int32)
            walls = np.zeros((C.SIZE_Y, C.SIZE_X), np.int32)

            for dy in [-1, 0, 1]:
                for dx in [-1, 0, 1]:
                    if dy != 0 or dx != 0:
                        stones += utils.isin(utils.translate(level.objects, dy, dx), G.STONE)
                        walls += utils.isin(utils.translate(level.objects, dy, dx), G.WALL)

            prio += (is_on_door & (stones > 3)) * 250
            prio += (np.stack([utils.translate(level.walkable, y, x).astype(np.int32)
                               for y, x in [(1, 0), (-1, 0), (0, 1), (0, -1)]]).sum(0) <= 1) * 250
            prio[(stones == 0) & (walls == 0)] = -np.inf

            prio[~level.walkable | (dis == -1)] = -np.inf

            if return_prio:
                return prio
            return prio >= prio_limit

        @Strategy.wrap
        def open_visit_search(search_prio_limit):
            yielded = False
            while 1:
                for py, px in self.agent.neighbors(self.agent.blstats.y, self.agent.blstats.x, diagonal=False, shuffle=False):
                    if self.agent.glyphs[py, px] in G.DOOR_CLOSED:
                        if not yielded:
                            yielded = True
                            yield True
                        open_neighbor_doors()
                        break

                to_visit = to_visit_func()
                to_search = to_search_func(search_prio_limit if search_prio_limit is not None else 0)

                # consider exploring tile only when there is a path to it
                dis = self.agent.bfs()
                to_explore = (to_visit | to_search) & (dis != -1)

                dynamic_search_fallback = False
                if not to_explore.any():
                    dynamic_search_fallback = True
                else:
                    # find all closest to_explore tiles
                    nonzero_y, nonzero_x = ((dis == dis[to_explore].min()) & to_explore).nonzero()
                    if len(nonzero_y) == 0:
                        dynamic_search_fallback = True

                if dynamic_search_fallback:
                    if search_prio_limit is not None and search_prio_limit >= 0:
                        if not yielded:
                            yield False
                        return

                    search_prio = to_search_func(return_prio=True)
                    if search_prio_limit is not None:
                        search_prio[search_prio < search_prio_limit] = -np.inf
                        search_prio[search_prio < search_prio_limit] = -np.inf
                        search_prio -= dis * np.isfinite(search_prio) * 100
                    else:
                        search_prio -= dis * 4

                    to_search = np.isfinite(search_prio)
                    to_explore = (to_visit | to_search) & (dis != -1)
                    if not to_explore.any():
                        if not yielded:
                            yield False
                        return
                    nonzero_y, nonzero_x = ((search_prio == search_prio[to_explore].max()) & to_explore).nonzero()

                if not yielded:
                    yielded = True
                    yield True

                # select random closest to_explore tile
                i = self.agent.rng.randint(len(nonzero_y))
                target_y, target_x = nonzero_y[i], nonzero_x[i]

                with self.agent.env.debug_tiles(to_explore, color=(0, 0, 255, 64)):
                    self.agent.go_to(target_y, target_x, debug_tiles_args=dict(
                        color=(255 * bool(to_visit[target_y, target_x]),
                               255, 255 * bool(to_search[target_y, target_x])),
                        is_path=True))
                    if to_search[target_y, target_x] and not to_visit[target_y, target_x]:
                        self.agent.search()

            assert search_prio_limit is not None

        return open_visit_search(search_prio_limit).preempt(self.agent, [
            self.agent.inventory.gather_items(),
        ])