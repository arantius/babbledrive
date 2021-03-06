"""Core pydoctor objects.

The two core objects are L{Documentable} and L{System}.  Instances of
(subclasses of) L{Documentable} represent the documentable 'things' in the
system being documented.  An instance of L{System} represents the whole system
being documented -- a System is a bad of Documentables, in some sense.
"""

import datetime
import imp
import os
import posixpath
import sys
import types
import __builtin__

# originally when I started to write pydoctor I had this idea of a big
# tree of Documentables arranged in an almost arbitrary tree.
#
# this was misguided.  the tree structure is important, to be sure,
# but the arrangement of the tree is far from arbitrary and there is
# at least some code that now relies on this.  so here's a list:
#
#   Packages can contain Packages and Modules
#   Modules can contain Functions and Classes
#   Classes can contain Functions (when they get called Methods) and Classes
#   Functions can't contain anything.

class Documentable(object):
    """An object that can be documented.

    The interface is a bit ridiculously wide.

    @ivar docstring: The object's docstring.  But also see docsources.
    @ivar system: The system the object is part of.
    @ivar prefix: ...
    @ivar parent: ...
    @ivar parentMod: ...
    @ivar name: ...
    @ivar document_in_parent_page: ...
    @ivar sourceHref: ...
    @ivar kind: ...
    """
    document_in_parent_page = False
    sourceHref = None

    @property
    def css_class(self):
        """A short, lower case description for use as a CSS class in HTML."""
        class_ = self.kind.lower().replace(' ', '')
        if self.privacyClass == PrivacyClass.PRIVATE:
            class_ += ' private'
        return class_

    def __init__(self, system, name, docstring, parent=None):
        self.system = system
        if parent is not None:
            if (parent.parent and isinstance(parent.parent, Package)
                and isinstance(parent, Module)
                and parent.name == '__init__'):
                self.prefix = parent.parent.fullName() + '.'
            else:
                self.prefix = parent.fullName() + '.'
        else:
            self.prefix = ''
        self.name = name
        self.docstring = docstring
        self.parent = parent
        self.parentMod = None
        self.setup()
        if not isinstance(self, Package):
            self.doctarget = self

    def setup(self):
        self.contents = {}
        self.orderedcontents = []
        self._name2fullname = {}

    def fullName(self):
        return self.prefix + self.name

    def __repr__(self):
        return "%s %r"%(self.__class__.__name__, self.fullName())

    def docsources(self):
        """Objects that can be consisdered as a source of documentation.

        The motivating example for having multiple sources is looking at a
        superclass' implementation of a method for documentation for a
        subclass'.
        """
        yield self

    def name2fullname(self, name):
        """XXX what is the difference between name2fullname,
        dottedNameToFullName and resolveDottedName??"""
        if name in self._name2fullname:
            return self._name2fullname[name]
        else:
            return self.parent.name2fullname(name)

    def _resolveName(self, name, verbose):
        """Helper for resolveDottedName."""
        system = self.system
        obj = self
        while obj:
            if name in obj.contents:
                return obj.contents[name]
            elif name in obj._name2fullname:
                fn = obj._name2fullname[name]
                o = system.allobjects.get(fn)
                if o is None:
                    for othersys in system.moresystems:
                        o = othersys.allobjects.get(fn)
                        if o is not None:
                            break
                if o is None and verbose > 0:
                    print "from %r, %r resolves to %r which isn't present in the system"%(
                        self.fullName(), name, fn)
                return o
            obj = obj.parent
        obj = self
        while obj:
            for n, fn in obj._name2fullname.iteritems():
                o2 = system.allobjects.get(fn)
                if o2 and name in o2.contents:
                    return o2.contents[name]
            obj = obj.parent
        if name in system.allobjects:
            return system.allobjects[name]
        for othersys in system.moresystems:
            if name in othersys.allobjects:
                return othersys.allobjects[name]
        if verbose > 0:
            print "failed to find %r from %r"%(name, self.fullName())
        return None

    def resolveDottedName(self, dottedname, verbose=None):
        """XXX what is the difference between name2fullname,
        dottedNameToFullName and resolveDottedName??"""
        if verbose is None:
            verbose = self.system.options.verbosity
        parts = dottedname.split('.')
        obj = self._resolveName(parts[0], verbose)
        if obj is None:
            self.system.msg(
                "resolveDottedName", "%s:%s invalid ref to %s" % (
                self.fullName(), self.linenumber, dottedname),
                thresh=-1)
            return obj
        for p in parts[1:]:
            if p not in obj.contents:
                self.system.msg(
                    "resolveDottedName", "%s:%s invalid ref to %s" % (
                        self.fullName(), self.linenumber, dottedname),
                    thresh=-1)
                return None
            obj = obj.contents[p]
        if verbose > 1:
            print dottedname, '->', obj.fullName(), 'in', self.fullName()
        return obj

    def dottedNameToFullName(self, dottedname):
        """XXX what is the difference between name2fullname,
        dottedNameToFullName and resolveDottedName??"""
        if '.' not in dottedname:
            start, rest = dottedname, ''
        else:
            start, rest = dottedname.split('.', 1)
            rest = '.' + rest
        obj = self
        while start not in obj._name2fullname:
            obj = obj.parent
            if obj is None or isinstance(obj, Package):
                return dottedname
        return obj._name2fullname[start] + rest

    @property
    def privacyClass(self):
        """How visible this object should be.

        @rtype: a member of the L{PrivacyClass} class/enum.
        """
        return self.system.privacyClass(self)

    @property
    def isVisible(self):
        """Is this object is so private as to be not shown at all?

        This is just a simple helper which defers to self.privacyClass.
        """
        return self.privacyClass != PrivacyClass.HIDDEN

    def __getstate__(self):
        # this is so very, very evil.
        # see doc/extreme-pickling-pain.txt for more.
        r = {}
        for k, v in self.__dict__.iteritems():
            if isinstance(v, Documentable):
                r['$'+k] = v.fullName()
            elif isinstance(v, list) and v:
                for vv in v:
                    if vv is not None and not isinstance(vv, Documentable):
                        r[k] = v
                        break
                else:
                    rr = []
                    for vv in v:
                        if vv is None:
                            rr.append(vv)
                        else:
                            rr.append(vv.fullName())
                    r['@'+k] = rr
            elif isinstance(v, dict) and v:
                for vv in v.itervalues():
                    if not isinstance(vv, Documentable):
                        r[k] = v
                        break
                else:
                    rr = {}
                    for kk, vv in v.iteritems():
                        rr[kk] = vv.fullName()
                    r['!'+k] = rr
            else:
                r[k] = v
        return r


class Package(Documentable):
    kind = "Package"
    def name2fullname(self, name):
        raise NameError
    def docsources(self):
        yield self.contents['__init__']
    @property
    def doctarget(self):
        return self.contents['__init__']

[UNPROCESSED, PROCESSING, PROCESSED] = range(3)

class Module(Documentable):
    kind = "Module"
    state = UNPROCESSED
    linenumber = 0
    def setup(self):
        super(Module, self).setup()
        self.all = None
    def name2fullname(self, name):
        if name in self._name2fullname:
            return self._name2fullname[name]
        elif name in __builtin__.__dict__:
            return name
        else:
            self.system.warning("optimistic name resolution", name)
            return name


class Class(Documentable):
    kind = "Class"
    def setup(self):
        super(Class, self).setup()
        self.bases = []
        self.rawbases = []
        self.baseobjects = []
        self.subclasses = []
    def allbases(self):
        for b in self.baseobjects:
            if b is None:
                continue
            yield b
            for b2 in b.allbases():
                yield b2


class Function(Documentable):
    document_in_parent_page = True
    kind = "Function"
    linenumber = 0
    def setup(self):
        super(Function, self).setup()
        if isinstance(self.parent, Class):
            self.kind = "Method"
    def docsources(self):
        yield self
        if not isinstance(self.parent, Class):
            return
        for b in self.parent.allbases():
            if self.name in b.contents:
                yield b.contents[self.name]

class PrivacyClass:
    """'enum' containing values indicating how private an object should be.

    @cvar HIDDEN: Don't show the object at all.
    @cvar PRIVATE: Show, but de-emphasize the object.
    @cvar VISIBLE: Show the object as normal.
    """

    HIDDEN = 0
    PRIVATE = 1
    VISIBLE = 2



class System(object):
    """A collection of related documentable objects.

    PyDoctor documents collections of objects, often the contents of a
    package.
    """

    Class = Class
    Module = Module
    Package = Package
    Function = Function
    # not done here for circularity reasons:
    #defaultBuilder = astbuilder.ASTBuilder
    sourcebase = None

    def __init__(self):
        self.allobjects = {}
        self.orderedallobjects = []
        self.rootobjects = []
        self.warnings = {}
        self.packages = []
        self.moresystems = []
        self.subsystems = []
        self.urlprefix = ''
        from pydoctor.driver import parse_args
        self.options, _ = parse_args([])
        self.options.verbosity = 3
        self.abbrevmapping = {}
        self.guessedprojectname = 'my project'
        self.epytextproblems = [] # fullNames of objects that failed to epytext properly
        self.verboselevel = 0
        self.needsnl = False
        self.once_msgs = set()
        self.unprocessed_modules = set()
        self.module_count = 0
        self.processing_modules = []
        self.buildtime = datetime.datetime.now()

    def verbosity(self, section=None):
        if isinstance(section, str):
            section = (section,)
        delta = max([self.options.verbosity_details.get(sect, 0) for sect in section])
        return self.options.verbosity + delta

    def progress(self, section, i, n, msg):
        if n is None:
            i = str(i)
        else:
            i = '%s/%s'%(i,n)
        if self.verbosity(section) == 0 and sys.stdout.isatty():
            print '\r'+i, msg,
            sys.stdout.flush()
            if i == n:
                self.needsnl = False
                print
            else:
                self.needsnl = True

    def msg(self, section, msg, thresh=0, topthresh=100, nonl=False, wantsnl=True, once=False):
        if once:
            if (section, msg) in self.once_msgs:
                return
            else:
                self.once_msgs.add((section, msg))
        if thresh <= self.verbosity(section) <= topthresh:
            if self.needsnl and wantsnl:
                print
            print msg,
            if nonl:
                self.needsnl = True
                sys.stdout.flush()
            else:
                self.needsnl = False
                print

    def resolveAlias(self, n):
        if '.' not in n:
            return n
        mod, clsname = n.rsplit('.', 1)
        if not mod:
            return mod
        systems = [self] + self.moresystems
        for system in systems:
            if mod in system.allobjects:
                break
        else:
            return n
        m = system.allobjects[mod]
        if isinstance(m, Package):
            m = m.contents['__init__']
        if not isinstance(m, Module):
            return n
        if clsname in m._name2fullname:
            newname = m.name2fullname(clsname)
            if newname == n:
                return newname
            for system in systems:
                if newname in system.allobjects:
                    return newname
            else:
                return self.resolveAlias(newname)
        else:
            return n

    def objForFullName(self, fullName):
        for sys in [self] + self.moresystems:
            if fullName in sys.allobjects:
                return sys.allobjects[fullName]
        return None

    def _warning(self, current, type, detail):
        if current is not None:
            fn = current.fullName()
        else:
            fn = '<None>'
        if self.options.verbosity > 0:
            print fn, type, detail
        self.warnings.setdefault(type, []).append((fn, detail))

    def objectsOfType(self, cls):
        """Iterate over all instances of C{cls} present in the system. """
        for o in self.orderedallobjects:
            if isinstance(o, cls):
                yield o

    def privacyClass(self, ob):
        if ob.name.startswith('_') and \
               not (ob.name.startswith('__') and ob.name.endswith('__')):
            return PrivacyClass.PRIVATE
        return PrivacyClass.VISIBLE

    def __setstate__(self, state):
        if 'abbrevmapping' not in state:
            state['abbrevmapping'] = {}
        # this is so very, very evil.
        # see doc/extreme-pickling-pain.txt for more.
        def lookup(name):
            for sys in [self] + self.moresystems + self.subsystems:
                if name in sys.allobjects:
                    return sys.allobjects[name]
            raise KeyError, name
        self.__dict__.update(state)
        for sys in [self] + self.moresystems + self.subsystems:
            if 'allobjects' not in sys.__dict__:
                return
        for sys in [self] + self.moresystems + self.subsystems:
            for obj in sys.orderedallobjects:
                for k, v in obj.__dict__.copy().iteritems():
                    if k.startswith('$'):
                        del obj.__dict__[k]
                        obj.__dict__[k[1:]] = lookup(v)
                    elif k.startswith('@'):
                        n = []
                        for vv in v:
                            if vv is None:
                                n.append(None)
                            else:
                                n.append(lookup(vv))
                        del obj.__dict__[k]
                        obj.__dict__[k[1:]] = n
                    elif k.startswith('!'):
                        n = {}
                        for kk, vv in v.iteritems():
                            n[kk] = lookup(vv)
                        del obj.__dict__[k]
                        obj.__dict__[k[1:]] = n

    def addObject(self, obj):
        """Add C{object} to the system."""
        if obj.parent:
            obj.parent.orderedcontents.append(obj)
            obj.parent.contents[obj.name] = obj
            obj.parent._name2fullname[obj.name] = obj.fullName()
        else:
            self.rootobjects.append(obj)
        self.orderedallobjects.append(obj)
        if obj.fullName() in self.allobjects:
            self.handleDuplicate(obj)
        else:
            self.allobjects[obj.fullName()] = obj

    # if we assume:
    #
    # - that svn://divmod.org/trunk is checked out into ~/src/Divmod
    #
    # - that http://divmod.org/trac/browser/trunk is the trac URL to the
    #   above directory
    #
    # - that ~/src/Divmod/Nevow/nevow is passed to pydoctor as an
    #   "--add-package" argument
    #
    # we want to work out the sourceHref for nevow.flat.ten.  the answer
    # is http://divmod.org/trac/browser/trunk/Nevow/nevow/flat/ten.py.
    #
    # we can work this out by finding that Divmod is the top of the svn
    # checkout, and posixpath.join-ing the parts of the filePath that
    # follows that.
    #
    #  http://divmod.org/trac/browser/trunk
    #                          ~/src/Divmod/Nevow/nevow/flat/ten.py

    def setSourceHref(self, mod):
        if self.sourcebase is None:
            mod.sourceHref = None
            return

        projBaseDir = mod.system.options.projectbasedirectory
        if projBaseDir is not None:
            mod.sourceHref = (
                self.sourcebase +
                mod.filepath[len(projBaseDir):])
            return

        trailing = []
        dir, fname = os.path.split(mod.filepath)
        while os.path.exists(os.path.join(dir, '.svn')):
            dir, dirname = os.path.split(dir)
            trailing.append(dirname)

        # now trailing[-1] would be 'Divmod' in the above example
        del trailing[-1]
        trailing.reverse()
        trailing.append(fname)

        mod.sourceHref = posixpath.join(mod.system.sourcebase, *trailing)

    def addModule(self, modpath, modname, parentPackage=None):
        mod = self.Module(self, modname, None, parentPackage)
        self.addObject(mod)
        self.progress(
            "addModule", len(self.orderedallobjects),
            None, "modules and packages discovered")
        mod.filepath = modpath
        self.unprocessed_modules.add(mod)
        self.module_count += 1
        self.setSourceHref(mod)

    def ensureModule(self, module_full_name):
        if module_full_name in self.allobjects:
            return self.allobjects[module_full_name]
        if '.' in module_full_name:
            parent_name, module_name = module_full_name.rsplit('.', 1)
            parent_package = self.ensurePackage(parent_name)
        else:
            parent_package = None
            module_name = module_full_name
        module = self.Module(self, module_name, None, parent_package)
        self.addObject(module)
        return module

    def ensurePackage(self, package_full_name):
        if package_full_name in self.allobjects:
            return self.allobjects[package_full_name]
        if '.' in package_full_name:
            parent_name, package_name = package_full_name.rsplit('.', 1)
            parent_package = self.ensurePackage(parent_name)
        else:
            parent_package = None
            package_name = package_full_name
        package = self.Package(self, package_name, None, parent_package)
        self.addObject(package)
        return package

    def _introspectThing(self, thing, parent, parentMod):
        for k, v in thing.__dict__.iteritems():
            if isinstance(v, (types.BuiltinFunctionType, type(dict.keys))):
                f = self.Function(self, k, v.__doc__, parent)
                f.parentMod = parentMod
                f.decorators = None
                f.argspec = ((), None, None, ())
                self.addObject(f)
            elif isinstance(v, type):
                c = self.Class(self, k, v.__doc__, parent)
                c.parentMod = parentMod
                self.addObject(c)
                self._introspectThing(v, c, parentMod)

    def introspectModule(self, py_mod, module_full_name):
        module = self.ensureModule(module_full_name)
        module.docstring = py_mod.__doc__
        self._introspectThing(py_mod, module, module)
        print py_mod

    def addPackage(self, dirpath, parentPackage=None):
        if not os.path.exists(dirpath):
            raise Exception("package path %r does not exist!"
                            %(dirpath,))
        if not os.path.exists(os.path.join(dirpath, '__init__.py')):
            raise Exception("you must pass a package directory to "
                            "addPackage")
        if parentPackage:
            prefix = parentPackage.fullName() + '.'
        else:
            prefix = ''
        package_name = os.path.basename(dirpath)
        package_full_name = prefix + package_name
        package = self.ensurePackage(package_full_name)
        package.filepath = dirpath
        self.setSourceHref(package)
        for fname in os.listdir(dirpath):
            fullname = os.path.join(dirpath, fname)
            if os.path.isdir(fullname):
                initname = os.path.join(fullname, '__init__.py')
                if os.path.exists(initname):
                    self.addPackage(fullname, package)
            elif not fname.startswith('.'):
                self.addModuleFromPath(package, fullname)

    def addModuleFromPath(self, package, path):
        for (suffix, mode, type) in imp.get_suffixes():
            if not path.endswith(suffix):
                continue
            module_name = os.path.basename(path[:-len(suffix)])
            if type == imp.C_EXTENSION:
                if not self.options.introspect_c_modules:
                    continue
                if package is not None:
                    module_full_name = "%s.%s" % (
                        package.fullName(), module_name)
                else:
                    module_full_name = module_name
                py_mod = imp.load_module(
                    module_full_name, open(path, 'rb'), path,
                    (suffix, mode, type))
                self.introspectModule(py_mod, module_full_name)
            elif type == imp.PY_SOURCE:
                self.addModule(path, module_name, package)
            break

    def handleDuplicate(self, obj):
        '''This is called when we see two objects with the same
        .fullName(), for example:

        class C:
            if something:
                def meth(self):
                    implementation 1
            else:
                def meth(self):
                    implementation 2

        The default is that the second definition "wins".
        '''
        i = 0
        fn = obj.fullName()
        while (fn + ' ' + str(i)) in self.allobjects:
            i += 1
        prev = self.allobjects[obj.fullName()]
        prev.name = obj.name + ' ' + str(i)
        self.allobjects[prev.fullName()] = prev
        self._warning(obj.parent, "duplicate", self.allobjects[obj.fullName()])
        self.allobjects[obj.fullName()] = obj
        return obj


    def getProcessedModule(self, modname):
        mod = self.allobjects.get(modname)
        if mod is None:
            return None
        if isinstance(mod, Package):
            return self.getProcessedModule(modname + '.__init__')
        if not isinstance(mod, Module):
            return None

        if mod.state == UNPROCESSED:
            self.processModule(mod)

        return mod


    def processModule(self, mod):
        assert mod.state == UNPROCESSED
        mod.state = PROCESSING
        if getattr(mod, 'filepath', None) is None:
            return
        builder = self.defaultBuilder(self)
        ast = builder.parseFile(mod.filepath)
        if  ast:
            self.processing_modules.append(mod.fullName())
            self.msg("processModule", "processing %s"%(self.processing_modules), 1)
            builder.processModuleAST(ast, mod)
            mod.state = PROCESSED
            head = self.processing_modules.pop()
            assert head == mod.fullName()
        self.unprocessed_modules.remove(mod)
        self.progress(
            'process',
            self.module_count - len(self.unprocessed_modules),
            self.module_count,
            "modules processed %s warnings"%(
            sum(len(v) for v in self.warnings.itervalues()),))


    def process(self):
        while self.unprocessed_modules:
            mod = iter(self.unprocessed_modules).next()
            self.processModule(mod)
