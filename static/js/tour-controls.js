// Tour Control Functions
// This file provides utility functions for managing the site tour

(function() {
    'use strict';

    // Make tour control functions globally available
    window.TourControls = {
        // Enable tour and show it on current page
        enableAndShow: function() {
            if (window.SiteTour && window.SiteTour.enableTour) {
                window.SiteTour.enableTour();
            }
        },

        // Disable tour (don't show anymore)
        disable: function() {
            if (window.SiteTour && window.SiteTour.disableTour) {
                window.SiteTour.disableTour();
            }
        },

        // Check if tour is currently disabled
        isDisabled: function() {
            try {
                return !!localStorage.getItem('siteTourGloballyDisabled');
            } catch (error) {
                return false;
            }
        },

        // Show tour on current page
        show: function() {
            if (window.SiteTour && window.SiteTour.start) {
                window.SiteTour.start();
            }
        }
    };

    // Set up event listener for site-tour-on button
    function setupTourButton() {
        const tourButton = document.getElementById('site-tour-on');
        if (tourButton) {
            tourButton.addEventListener('click', function(e) {
                e.preventDefault();
                window.TourControls.enableAndShow();
            });
        }
    }

    // Initialize button listener when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setupTourButton);
    } else {
        setupTourButton();
    }
})();
