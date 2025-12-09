(function() {
    'use strict';

    const mobileMenuToggle = document.getElementById('mobileMenuToggle');
    const mobileMenu = document.getElementById('mobileMenu');
    const mobileMenuBackdrop = document.getElementById('mobileMenuBackdrop');
    const mobileMenuClose = document.getElementById('mobileMenuClose');
    const body = document.body;

    if (!mobileMenuToggle || !mobileMenu || !mobileMenuBackdrop) {
        return;
    }

    mobileMenu.classList.remove('show');
    mobileMenuBackdrop.classList.remove('show');
    body.style.overflow = '';

    function openMenu() {
        mobileMenu.classList.add('show');
        mobileMenuBackdrop.classList.add('show');
        body.style.overflow = 'hidden';
        
        const icon = mobileMenuToggle.querySelector('.icon');
        if (icon) {
            icon.innerHTML = `
                <path d="M2.146 2.854a.5.5 0 1 1 .708-.708L8 7.293l5.146-5.147a.5.5 0 0 1 .708.708L8.707 8l5.147 5.146a.5.5 0 0 1-.708.708L8 8.707l-5.146 5.147a.5.5 0 0 1-.708-.708L7.293 8 2.146 2.854Z"/>
            `;
        }
    }

    function closeMenu() {
        mobileMenu.classList.remove('show');
        mobileMenuBackdrop.classList.remove('show');
        body.style.overflow = '';
        
        const icon = mobileMenuToggle.querySelector('.icon');
        if (icon) {
            icon.innerHTML = `
                <path fill-rule="evenodd" d="M2.5 12a.5.5 0 0 1 .5-.5h10a.5.5 0 0 1 0 1H3a.5.5 0 0 1-.5-.5zm0-4a.5.5 0 0 1 .5-.5h10a.5.5 0 0 1 0 1H3a.5.5 0 0 1-.5-.5zm0-4a.5.5 0 0 1 .5-.5h10a.5.5 0 0 1 0 1H3a.5.5 0 0 1-.5-.5z"/>
            `;
        }
    }

    function toggleMenu() {
        if (mobileMenu.classList.contains('show')) {
            closeMenu();
        } else {
            openMenu();
        }
    }

    mobileMenuToggle.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        toggleMenu();
    });

    if (mobileMenuClose) {
        mobileMenuClose.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            closeMenu();
        });
    }

    mobileMenuBackdrop.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        closeMenu();
    });

    const mobileMenuLinks = mobileMenu.querySelectorAll('.nav-link');
    mobileMenuLinks.forEach(function(link) {
        link.addEventListener('click', function() {
            closeMenu();
        });
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && mobileMenu.classList.contains('show')) {
            closeMenu();
        }
    });

    window.addEventListener('resize', function() {
        if (window.innerWidth >= 992 && mobileMenu.classList.contains('show')) {
            closeMenu();
        }
    });
})();

