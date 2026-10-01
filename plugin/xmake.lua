-- FoggyMap F4SE plugin.
--
-- Build layout and flags follow HighFPSPhysicsFix, which is the reference for a
-- single DLL that loads on the old-gen 1.10.163 runtime (F4SE 0.6.23) as well as
-- next-gen, via Address Library and the Dear-Modding-FO4 CommonLibF4 fork.
--
--   xmake                                              -- build only
--   xmake f --deploy_dir="<MO2 mods folder>/FoggyMap"  -- also copy into MO2
--   xmake

set_xmakever("3.0.0")

set_project("FoggyMap")
set_version("0.1.0")
set_license("MIT")

set_languages("c++23")
set_encodings("utf-8")
set_runtimes("MT")

add_rules("mode.debug", "mode.releasedbg")
-- Only modes with a rule are allowed: the rule is what gives each target its own .pdb.
-- Plain "release" has none, which left compiles sharing vc140.pdb and racing on it.
set_allowedmodes("debug", "releasedbg")
set_defaultmode("releasedbg")

includes("extern/CommonLibF4")

option("deploy_dir")
    set_default("")
    set_showmenu(true)
    set_description("MO2 mod folder to copy the built DLL + INI into (empty = skip)")
option_end()

target("FoggyMap")
    set_kind("shared")
    set_arch("x64")

    add_deps("commonlibf4")

    add_files("src/**.cpp")
    add_headerfiles("src/**.h")
    add_includedirs("src")
    set_pcxxheader("src/PCH.h")

    -- Support all three runtimes so the DLL is not tied to one game version.
    add_defines("_UNICODE", "COMMONLIB_RUNTIMECOUNT=3")

    add_cxxflags(
        "/sdl",
        "/W4",
        "/GS",
        "/guard:cf",
        "/utf-8",
        "/permissive-",
        "/Zc:preprocessor",
        "/Zc:__cplusplus",
        "/Zc:throwingNew",
        "/Zc:inline",
        "/wd4200",
        "/wd4100",
        { force = true, tools = { "cl" } }
    )
    add_ldflags(
        "/DYNAMICBASE",
        "/NXCOMPAT",
        "/HIGHENTROPYVA",
        "/guard:cf",
        { force = true, tools = { "link" } }
    )

    -- Drop the built DLL straight into its MO2 mod folder so it can be toggled
    -- there like any other mod, leaving the game directory untouched.
    after_build(function (target)
        local deploy_dir = get_config("deploy_dir")
        if not deploy_dir or deploy_dir == "" then
            return
        end
        local plugins_dir = path.join(deploy_dir, "F4SE", "Plugins")
        os.mkdir(plugins_dir)
        os.cp(target:targetfile(), plugins_dir)
        local pdb = path.join(target:targetdir(), target:name() .. ".pdb")
        if os.isfile(pdb) then
            os.cp(pdb, plugins_dir)
        end
        -- Never overwrite a deployed ini: it holds the user's settings, and clobbering
        -- them on every build silently reverts whatever they just turned on.
        local deployed_ini = path.join(plugins_dir, "FoggyMap.ini")
        if os.isfile("FoggyMap.ini") and not os.isfile(deployed_ini) then
            os.cp("FoggyMap.ini", deployed_ini)
            cprint("${bright green}deploy: ${clear}installed a fresh FoggyMap.ini")
        elseif os.isfile(deployed_ini) then
            cprint("${yellow}deploy: ${clear}kept your existing FoggyMap.ini")
        end
        cprint("${bright green}deploy: ${clear}copied to %s", plugins_dir)
    end)
