#!/usr/bin/env python
# coding: utf-8


import logging

import common
import lt_common
import lt_misc
import logparser

_logger = logging.getLogger(__name__.rpartition(".")[-1])


class LTGenImport(lt_common.LTGen):

    def __init__(self, table, sym, filename, mode, lp):
        super(LTGenImport, self).__init__(table, sym)
        self._table = table
        self._d_def = common.IDDict(lambda x: tuple(x))
        self.searchtree = lt_misc.LTSearchTree(sym)
        self._open_def(filename, mode, lp)

    def _open_def(self, filename, mode, lp):
        cnt = 0
        with open(filename, 'r') as f:
            for line in f:
                if mode == "plain":
                    mes = line.rstrip("\n")
                elif mode == "ids":
                    line = line.rstrip("\n")
                    mes = line.partition(" ")[2].strip()
                else:
                    raise ValueError("imvalid import_mode {0}".format(
                            self.mode))
                ltw, lts = lp.split_message(mes)
                defid = self._d_def.add(ltw)
                self.searchtree.add(defid, ltw)
                cnt += 1
        _logger.info("{0} template imported".format(cnt))

    def process_line(self, l_w, l_s):
        defid = self.searchtree.search(l_w)
        if defid is None:
            _logger.warning(
                    "No log template found for message : {0}".format(l_w))
            return None, None
        else:
            tpl = self._d_def.get(defid)
            if self._table.exists(tpl):
                tid = self._table.get_tid(tpl)
                return tid, self.state_unchanged
            else:
                tid = self._table.add(tpl)
                return tid, self.state_added

