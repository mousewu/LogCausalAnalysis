#!/usr/bin/env python
# coding: utf-8

"""#
"""

import sys
import os
import datetime
import logging
import cPickle as pickle
import numpy as np

import config
import dtutil
import log_db
import log2event
#import calc
#import log_db
#import timelabel

_logger = logging.getLogger(__name__.rpartition(".")[-1])


#class IDFilter():
#
#    def __init__(self, def_fn):
#        self.fids = set()
#        if isinstance(def_fn, list):
#            for fn in def_fn:
#                if os.path.exists(fn):
#                    self._open_def(fn)
#                else:
#                    self._exception_notfound(def_fn)
#        elif isinstance(def_fn, str):
#            if os.path.exists(def_fn):
#                self._open_def(def_fn)
#            else:
#                self._exception_notfound(def_fn)
#        else:
#            raise TypeError("Invalid filter definition name")
#
#    def _exception_notfound(self, def_fn):
#        _logger.warning("Filter definition file {0} not found".format(fn))
#
#    def _open_def(self, fn):
#        with open(fn, 'r') as f:
#            for line in f:
#                line = line.strip("\n")
#                if line == "":
#                    pass
#                elif line[0] == "#":
#                    pass
#                else:
#                    self.fids.add(int(line))
#
#    def isremoved(self, nid):
#        return nid in self.fids


class EventFilter():
    """Record and restore event periodicity to filter log events.
    An event is identified with ltgid(int) and host(str).

    Attributes:
        filename (str)
        default_th (float)
        d_ev (dict)
    """

    def __init__(self, default_th, filename):
        self.filename = filename
        self.default_th = default_th
        self.d_ev = {} # key = (ltgid, host), val = (dur, corr)

    def reset(self):
        """Remove existing record of event periodicity.
        """
        if os.path.exists(self.filename):
            os.remove(self.filename)

    def add(self, ltgid, host, dur, corr):
        """Register 1 event and its result of periodicity test.
        
        Args:
            ltgid (int)
            host (str)
            dur (datetime.timedelta)
            corr (float)
        """
        key = (ltgid, host)
        self.d_ev[key] = (dur, corr)

    def filtered(self, ltgid, host, th = None):
        """Get whether an event is periodic or not.
        
        Args:
            ltgid (int)
            host (str)
            th (Optional[float]): Used threshold of correlation
                to test event periodicity.

        Returns:
            bool: True if the event is periodic.
        """
        if th is None:
            th = self.default_th
        key = (ltgid, host)
        assert self.d_ev.has_key(key)
        val = self.d_ev[key][1]
        if val is None:
            return False
        else:
            return self.d_ev[key] > th

    def interval(self, ltgid, host):
        """Get most reasonable periodicity interval. This function returns
        none only if no data registered for the event.
        
        Args:
            ltgid (int)
            host (str)

        Returns:
            datetime.timedelta: Most reasonable interval for periodicity test.
        """
        key = (ltgid, host)
        if self.d_ev.has_key(key):
            return self.d_ev[key][0]
        else:
            return None

    def load(self):
        """Restore event periodicity data from a serialized file."""
        with open(self.filename, 'r') as f:
            self.d_ev = pickle.load(f)

    def dump(self):
        """Serialize event periodicity with cPickle."""
        obj = self.d_ev
        with open(self.filename, 'w') as f:
            pickle.dump(obj, f)


def init_evfilter(conf, verbose = False):
    # initialize 'periodic-whole' filter object
    if not conf.getboolean("dag", "usefilter"):
        return 
    _logger.info("start initializing evfilter")

    per_count = conf.getint("filter", "periodic_count")
    per_term = conf.getdur("filter", "periodic_term")
    per_th = conf.getfloat("filter", "periodic_th")
    corr_th = conf.getfloat("filter", "self_corr_th")
    corr_diff = [config.str2dur(diffstr) for diffstr
                 in conf.gettuple("filter", "self_corr_diff")]
    corr_bin = conf.getdur("filter", "self_corr_bin")

    ld = log_db.LogData(conf)
    temp_fn = conf.get("filter", "temp_filter_data")
    evf = EventFilter(corr_th, filename = temp_fn)
    evf.reset()
    
    term = conf.getterm("filter", "sampling_term")
    if term is None:
        term = conf.getterm("dag", "whole_term")
        if term is None:
            top_dt, end_dt = ld.whole_term()
        else:
            top_dt, end_dt = term
    else:
        top_dt, end_dt = term

    # generate interval candidates with periodic-check
    edict, evmap = log2event.log2event(conf, ld, top_dt, end_dt, "all")
    s_interval = set()
    for eid, l_dt in edict.iteritems():
        if periodic_term(l_dt, per_count, per_term):
            temp = interval(l_dt, per_th)
            if temp is not None:
                s_interval.add(temp)
    new_corr_diff = [datetime.timedelta(seconds = sec) for sec in s_interval]
    mes = "interval candidates : given ({0}), found ({1})".format(\
            ", ".join([str(a).partition(",")[0] for a in corr_diff]),
            ", ".join([str(a).partition(",")[0] for a
                in sorted(new_corr_diff, key = lambda x: x.total_seconds())]))
    _logger.info(mes)
    if verbose:
        print(mes)

    # construct filter object
    corr_diff = corr_diff + new_corr_diff
    for eid, l_dt in edict.iteritems():
        _logger.info("processing event {0}".format("eid"))
        data = dtutil.auto_discretize(l_dt, corr_bin)
        l_ret = [(diff, self_corr(data, diff, corr_bin)) for diff in corr_diff]
        if len(l_ret) > 0:
            dur, corr = max(l_ret, key = lambda x: x[1])
        else:
            dur, corr = (None, None)
        for dur, corr in l_ret:
            _logger.info("lag {0} : {1}".format(dur, corr))

        info = evmap.info(eid) 
        evf.add(info.gid, info.host, dur, corr)
        mes = "event [{0} {1}, host {2}] : {3} ({4})".format(
                    evmap.gid_name, info.gid, info.host, corr, dur)
        _logger.info(mes)
        if verbose:
            print(mes)

    evf.dump()
    _logger.info("initializing evfilter done")
    
    return


def periodic_events(conf, edict, evmap):
    """Get identifiers of periodic events. This function only see filter
    definition object that is initialized in init_filter().

    Args:
        conf (config.ExtendedConfigParser): A common configuration object.
        edict (Dict[List[datetime.datetime]]): Event appearance data.
        evmap (log2event.LogEventIDMap): Event definition data.

    Returns:
        List[int, datetime.timedelta]: A sequence of periodic event
            identifiers and its periodicity interval.
    """
   
    ret = []
    corr_th = conf.getfloat("filter", "self_corr_th")
    temp_fn = conf.get("filter", "temp_filter_data")
    pf = EventFilter(corr_th, filename = temp_fn)
    pf.load()
    per_count = conf.getint("filter", "periodic_count")
    per_term = conf.getdur("filter", "periodic_term")
    for eid, l_dt in edict.iteritems():
        if periodic_term(l_dt, per_count, per_term):
            info = evmap.info(eid)
            if pf.filtered(info.gid, info.host, corr_th):
                interval = pf.interval(info.gid, info.host)
                ret.append((eid, interval))
    return ret


#def periodicity(conf, edict, evmap, l_filter):
#    if len(l_filter) == 0:
#        return edict, evmap
#    #if "file" in l_filter:
#    #    ff = IDFilter(conf.getlist("filter", "filter_name"))
#    if "periodic-whole" in l_filter:
#        corr_th = conf.getfloat("filter", "self_corr_th")
#        temp_fn = conf.get("filter", "temp_filter_data")
#        pf = EventFilter(corr_th, filename = temp_fn)
#        pf.load()
#    per_count = conf.getint("filter", "periodic_count")
#    per_term = conf.getdur("filter", "periodic_term")
#    if "periodic" in l_filter:
#        per_th = conf.getfloat("filter", "periodic_th")
#    if "self-corr" in l_filter:
#        corr_th = conf.getfloat("filter", "self_corr_th")
#        corr_diff = [config.str2dur(diffstr) for diffstr
#                     in conf.gettuple("filter", "self_corr_diff")]
#        corr_bin = conf.getdur("filter", "self_corr_bin")
#
#    result = []
#    for eid, l_dt in edict.iteritems():
#        #if "file" in l_filter:
#        #    if ff.isremoved(eid):
#        #        result.append((None, ))
#        #        l_eid.append(eid)
#        #        continue
#        if periodic_term(l_dt, per_count, per_term):
#            if "periodic-whole" in l_filter:
#                info = evmap.info(eid)
#                ltgid = info.ltgid
#                host = info.host
#                if pf.filtered(ltgid, host, corr_th):
#                    interval = pf.interval(ltgid, host)
#                    result.append((interval, eid))
#                    continue
#            if "periodic" in l_filter:
#                temp = interval(l_dt, per_th)
#                if temp is not None:
#                    result.append((temp, eid))
#                    continue
#            if "self-corr" in l_filter:
#                dur, corr = self_correlation(l_dt, corr_diff, corr_bin)
#                if corr is not None and corr > corr_th:
#                    result.append((dur, eid))
#                    continue
#
#    return l_eid


# To filter periodic log

def periodic_term(l_dt, count, term, verbose = False):
    if len(l_dt) < count:
        if verbose:
            print("Event appearance is too small, skip periodicity test")
        return False
    elif max(l_dt) - min(l_dt) < term:
        if verbose:
            print("Event appearing term is too short, skip periodicity test")
        return False
    else:
        return True


def interval(l_dt, threshold = 0.5, verbose = False):
    # args
    #   l_dt : list of datetime.datetime
    #   threshold : threshold value for standard deviation
    #   verbose : output calculating infomation to stdout
    # return
    #   interval(int) if the given l_dt have stable interval
    #   or return None

    if len(l_dt) <= 2:
    #    # len(l_dt) < 2 : no interval will be found
    #    # len(l_dt) == 2 : only 1 interval that not seem periodic...
        return None
    l_interval = []
    prev_dt = None
    for dt in sorted(l_dt):
        if prev_dt is not None:
            diff = (dt - prev_dt).total_seconds()
            l_interval.append(diff)
        prev_dt = dt

    dist = np.array(l_interval)
    std = np.std(dist)
    mean = np.mean(dist)

    if verbose:
        print("std {0}, mean {1}, median {2}".format(std, mean,
                                                     np.median(dist)))

    if mean == 0:
        # mean == 0 : multiple message in 1 time, not seem periodic
        return None
    if (std / mean) < threshold:
        return int(np.median(dist))
    else:
        return None


#def self_correlation(l_dt, l_diff, binsize):
#    """
#    Returns:
#        float: Interval of periodicity.
#        float: Maximum correlation value with given time lag.
#    """
#    data = auto_discretize(l_dt, binsize)
#
#    l_ret = []
#    for diff in l_diff:
#        val = self_corr(data, diff, binsize)
#        l_ret.append((diff, val))
#
#    if len(l_ret) > 0:
#        return max(l_ret, key = lambda x: x[1])
#    else:
#        return None, None


def self_corr(data, diff, binsize):
    """
    Args:
        data (List[datetime.datetime])
        diff (datetime.timedelta)
        binsize (datetime.timedelta)

    Returns:
        float: Self-correlation coefficient with given lag.
    """
    binnum = int(diff.total_seconds() / binsize.total_seconds())
    if len(data) <= binnum * 2:
        return 0.0
    else:
        data1 = data[:len(data) - binnum]
        data2 = data[binnum:]
        assert len(data1) == len(data2)
        return np.corrcoef(np.array(data1), np.array(data2))[0, 1]


#def discretize_dt(l_dt, binsize):
#    """
#    Args:
#        l_dt (List[datetime.datetime])
#        binsize (datetime.timedelta)
#    """
#    if binsize == datetime.timedelta(seconds = 1):
#        return l_dt
#    else:
#        top_dt = dtutil.adj_sep(min(l_dt), binsize)
#        end_dt = dtutil.radj_sep(max(l_dt), binsize)
#        l_label = dtutil.label(top_dt, end_dt, binsize)
#        return dtutil.discretize(l_dt, l_label, binarize = False)


#def test_init_filter(conf):
#    init_evfilter(conf, verbose = False)
#    evf = EventFilter(corr_th, filename = temp_fn)


def test_filter(conf, area = "all", limit = 10):
    ld = log_db.LogData(conf)
    w_term = conf.getterm("dag", "whole_term")
    if w_term is None:
        w_term = ld.whole_term()
        print w_term
    term = conf.getdur("dag", "unit_term")
    diff = conf.getdur("dag", "unit_diff")
    dur = conf.getdur("dag", "stat_bin")

    l_filter = conf.gettuple("dag", "use_filter")
    print l_filter
    #if "file" in l_filter:
    #    ff = IDFilter(conf.getlist("filter", "filter_name"))
    per_count = conf.getint("filter", "periodic_count")
    per_term = conf.getdur("filter", "periodic_term")
    if "periodic" in l_filter:
        per_th = conf.getfloat("filter", "periodic_th")
    if "self-corr" in l_filter:
        corr_th = conf.getfloat("filter", "self_corr_th")
        corr_diff = [config.str2dur(diffstr) for diffstr
                     in conf.gettuple("filter", "self_corr_diff")]
        corr_bin = conf.getdur("filter", "self_corr_bin")

    for top_dt, end_dt in dtutil.iter_term(w_term, term, diff):
        print("[Testing {0} - {1}]".format(top_dt, end_dt))
        s_eid = set()
        edict, evmap = log2event.log2event(conf, ld, top_dt, end_dt, area)
        for eid, l_dt in edict.iteritems():
            info = evmap.info(eid)
            print("Event {0} : ltgid {1} in host {2} ({3})".format(eid,
                    info.ltgid, info.host, len(l_dt)))
            print ld.show_log_repr(head = limit, ltgid = info.ltgid,
                    top_dt = top_dt, end_dt = end_dt,
                    host = info.host, area = area)
            #if "file" in l_filter:
            #    if ff.isremoved(eid):
            #        print("found in definition file, removed")
            #        s_eid.add(eid)
            if periodic_term(l_dt, per_count, per_term, verbose = True):
                if "periodic" in l_filter:
                    temp = interval(l_dt, per_th, verbose = True)
                    if temp is not None:
                        print("rule [periodic] safisfied, removed")
                        print("interval : {0}".format(temp))
                        s_eid.add(eid)
                if "self-corr" in l_filter:
                    #dur, corr = self_correlation(l_dt, corr_diff, corr_bin)
                    data = dtutil.auto_discretize(l_dt, corr_bin)
                    l_val = [self_corr(data, diff, corr_bin)
                            for diff in corr_diff]
                    corr = max(l_val)
                    print("self-correlation : {0}".format(corr))
                    if corr > corr_th:
                        print("rule [self-corr] satisfied, removed")
                        s_eid.add(eid)
            print
        print("[Summary in term {0} - {1}]".format(top_dt, end_dt))
        print("  {0} events found, {1} events filtered, {2} remains".format(\
                len(edict), len(s_eid), len(edict) - len(s_eid)))
        print


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: {0} config (area)".format(sys.argv[0]))
    confname = sys.argv[1]
    if len(sys.argv) >= 3:
        area = sys.argv[2]
    else:
        area = "all"
    conf = config.open_config(confname)
    config.set_common_logging(conf, _logger, [])
    #test_filter(conf, area)


