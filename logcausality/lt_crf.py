#!/usr/bin/env python
# coding: utf-8

"""
lt_crf.py needs CRF++ (https://taku910.github.io/crfpp/)
and python wrapper in CRF++.
"""

import sys
import os
import cPickle as pickle
import CRFPP
import logging

import common
import config
import lt_common
import strutil
#import logparser

_logger = logging.getLogger(__name__.rpartition(".")[-1])
DEFAULT_FEATURE_TEMPLATE = "/".join((os.path.dirname(__file__),
        "crf_template"))


class LTGenCRF(lt_common.LTGen):

    def __init__(self, table, sym, conf):
        super(LTGenCRF, self).__init__(table, sym)
        model = conf.get("log_template_crf", "model_filename")
        self._middle = conf.get("log_template_crf", "middle_label")
        
        self._crf = CRFPP.Tagger("-m " + model + " -v 3 -n2")
        if self._middle == "re":
            import label_word
            self._lwobj = label_word.LabelWord(conf)

    def _middle_label(self, w):
        if self._middle == "re":
            return self._lwobj.label(w)
        else:
            return "W"

    def process_line(self, l_w, l_s):
        self._crf.clear()
        for w in l_w:
            label = self._middle_label(w)
            self._crf.add("{0} {1}".format(w, label))
        self._crf.parse()

        tpl = []
        for wid, w in enumerate(l_w):
            label = self._crf.y2(wid)
            if label == "D":
                tpl.append(w)
            elif label == "V":
                tpl.append(self._sym)
            else:
                raise ValueError("crf label invalid ({0})".format(label))

        if self._table.exists(tpl):
            tid = self._table.get_tid(tpl)
            return tid, self.state_unchanged
        else:
            tid = self._table.add(tpl)
            return tid, self.state_added


def train(conf, train_fn = None):
    model_fn = conf.get("log_template_crf", "model_filename")
    template_fn = conf.get("log_template_crf", "feature_template")
    if template_fn == "":
        template_fn = DEFAULT_FEATURE_TEMPLATE
    if train_fn is None:
        train_fn = conf.get("log_template_crf", "train_filename")

    cmd = "crf_learn {0} {1} {2}".format(template_fn, train_fn, model_fn)
    ret, stdout, stderr = common.call_process(cmd)
    if not ret == 0:
        raise ValueError("crf_learn failed")
    print stdout
    sys.stderr.write(stderr)
    return


def lt2trainsource(conf, fn = None):
    import log_db
    ld = log_db.LogData(conf)
    sym = conf.get("log_template", "variable_symbol")
    if fn is None:
        fn = conf.get("log_template_crf", "train_filename")
    ret = []
    for lt in ld.iter_lt():
        l_train = []
        tpl = lt.ltw
        ex = ld.iter_lines(ltid = lt.ltid).next().l_w
        for w_tpl, w_ex in zip(tpl, ex):
            if w_tpl == sym:
                l_train.append((w_ex, "V"))
            else:
                l_train.append((w_tpl, "D"))
        ret.append("\n".join(["{0[0]} {0[1]} {0[1]}".format(train)
                for train in l_train]))
    with open(fn, "w") as f:
        f.write("\n\n".join(ret))


def generate_lt_from_file(conf, fn):
    _logger.info("job for ({0}) start".format(fn))
    
    import logparser
    lp = logparser.LogParser(conf)
    table = lt_common.TemplateTable()
    sym = conf.get("log_template", "variable_symbol")
    d_symlist = {}
    ltgen = LTGenCRF(table, sym, conf)
    
    with open(fn, "r") as f:
        for line in f:
            dt, org_host, l_w, l_s = lp.process_line(line)
            if l_w is None: continue
            l_w = [strutil.add_esc(w) for w in l_w]
            tid, dummy = ltgen.process_line(l_w, l_s)
            d_symlist[tid] = l_s

    ret = []
    for tid in table.tids():
        tpl = table.get_template(tid)
        l_s = d_symlist[tid]
        ret.append((tpl, l_s))

    _logger.info("job for ({0}) done".format(fn))
    return ret


def wrapper_mp(args):
    conf, fn = args
    return generate_lt_from_file(conf, fn)


def generate_lt_pal(conf, targets, pal):
    
    import multiprocessing
    #import log_db
    #ld = log_db.LogData(conf)

    timer = common.Timer("lt_crf task", output = _logger)
    timer.start()
    pool = multiprocessing.Pool(pal)
    l_callback = pool.map(wrapper_mp, [(conf, fn) for fn in targets])
    timer.stop()

    with open("temp_crf_dump", "w") as f:
        pickle.dump(l_callback, f)

    timer = common.Timer("lt_crf postprocessing task", output = _logger)
    timer.start()
    sym = conf.get("log_template", "variable_symbol")
    lttable = lt_common.LTTable(sym)
    table = lt_common.TemplateTable()
    for ret in l_callback:
        for tpl, l_s in ret:
            if table.exists(tpl):
                pass
            else:
                tid = table.add(tpl)
                lt = lt_common.LogTemplate(tid, tid, tpl, l_s, 0, sym)
                lttable.add_lt(lt)

    with open("temp_crf_template", "w") as f:
        pickle.dump(lttable, f)

    timer.stop()
    for ltline in lttable:
        print ltline


if __name__ == "__main__":
    import log_db
    import optparse
    usage = "usage: {0} [options] mode".format(sys.argv[0])
    op = optparse.OptionParser(usage)
    op.add_option("-c", "--config", action="store",
            dest="conf", type="string", default=config.DEFAULT_CONFIG_NAME,
            help="configuration file path")
    op.add_option("-r", action="store_true", dest="recur",
            default=False, help="search log file recursively")
    op.add_option("-p", "--parallel", action="store", dest="pal", type="int",
            default=1, help="multiprocessing for make")
    op.add_option("--debug", action="store_true", dest="debug",
            default=False, help="set logging level to DEBUG")
    options, args = op.parse_args()

    conf = config.open_config(options.conf)
    lv = logging.DEBUG if options.debug else logging.INFO
    config.set_common_logging(conf, _logger, [], lv = lv)
    
    if len(args) == 0:
        sys.exit(usage)
    mode = args.pop(0)
    if mode == "make":
        targets = log_db._get_targets(conf, args, options.recur)
        generate_lt_pal(conf, targets, options.pal)
    elif mode == "make_test":
        print "\n".join([" ".join(tpl) for tpl, l_w
                in generate_lt_from_file(conf, args[0])])
    elif mode == "train":
        train(conf)
    elif mode == "lt2trainsource":
        lt2trainsource(conf)
    else:
        sys.exit("Invalid argument")



